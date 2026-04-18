import chromadb
from chromadb.utils import embedding_functions

# Initialize ChromaDB in the local directory
chroma_client = chromadb.PersistentClient(path="./chroma_db")

# Use a default sentence transformer for easy, lightweight embeddings
sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

# Get or create the collection for storing user memories
memory_collection = chroma_client.get_or_create_collection(
    name="trisoul_memory",
    embedding_function=sentence_transformer_ef
)

def save_interaction(user_id: str, session_id: str, user_message: str, ai_response: str) -> None:
    """Saves a single conversation turn into the vector database."""
    interaction_text = f"User: {user_message}\nAI: {ai_response}"
    
    import uuid
    doc_id = str(uuid.uuid4())
    
    memory_collection.add(
        documents=[interaction_text],
        metadatas=[{"user_id": user_id, "session_id": session_id, "type": "interaction"}],
        ids=[doc_id]
    )

def get_relevant_history(user_id: str, session_id: str, current_query: str, n_results: int = 3, allow_cross_session: bool = False) -> str:
    """Retrieves the most semantically relevant past interactions for this user."""
    
    # 1. Isolation Context Firewall for Vector Search
    where_clause = {"user_id": user_id}
    if not allow_cross_session:
        where_clause = {
            "$and": [
                {"user_id": {"$eq": user_id}},
                {"session_id": {"$eq": session_id}}
            ]
        }
    
    results = memory_collection.query(
        query_texts=[current_query],
        n_results=n_results,
        where=where_clause
    )
    
    docs = results.get('documents', [[]])[0]
    
    if not docs:
        return "No relevant past memories found."
        
    formatted_memory = "\n\n".join(docs)
    return f"RELEVANT PAST MEMORIES WITH THIS USER:\n{formatted_memory}"
