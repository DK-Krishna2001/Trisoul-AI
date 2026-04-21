from diagrams import Diagram, Cluster, Edge

from diagrams.onprem.client import User, Client
from diagrams.onprem.compute import Server
from diagrams.gcp.database import Firestore
from diagrams.onprem.network import Internet
from diagrams.firebase.base import Firebase
from diagrams.programming.framework import Fastapi

with Diagram("Trisoul Parallel StateGraph Architecture", show=False, filename="trisoul_parallel_architecture", outformat="png", direction="TB"):
    user = User("Patient / User")
    
    with Cluster("Client Interfaces"):
        ui = Client("Web UI (Vanilla JS)")
        speech = Client("Web Speech API")
        whatsapp = Client("WhatsApp (Twilio)")
        auth = Firebase("Firebase Auth")

    with Cluster("Core Backend Layer"):
        gateway = Fastapi("FastAPI Router Gateway")
        workers = Server("Background Evaluators")
        doc_parser = Server("Document Parser (PyMuPDF)")

    with Cluster("Intelligence Engine (Parallel StateGraph)"):
        mem = Server("Memory & ChromaDB RAG\n(all-MiniLM-L6-v2)")
        
        router = Server("Fast Router Node\n(llama-3.1-8b-instant)")
        
        with Cluster("Fast Utility Bypass"):
            emergency = Server("Emergency Protocol")
            locator = Internet("Google Maps Locator")
            twilio_api = Internet("Twilio Call API")
        
        with Cluster("Parallel Therapy Fan-out"):
            clinical = Server("Clinical Therapy Insight\n(gpt-oss-120b & gpt-4o-mini)")
            sentiment = Server("Sentiment Analysis\n(llama-3.1-8b-instant)")
            
        synthesis = Server("Synthesis Node\n(openai/gpt-oss-120b)")

    db = Firestore("Firestore Database")

    # Workflow Connections
    user >> ui
    user >> speech
    user >> whatsapp
    ui >> auth
    
    # Ingestion
    ui >> Edge(label="/ask (Text/Files)") >> gateway
    speech >> Edge(label="/transcribe") >> gateway
    whatsapp >> Edge(label="Twilio Webhook") >> gateway
    
    # Backend processing
    gateway >> doc_parser >> mem
    gateway >> mem
    
    # Router Step
    mem >> router
    
    # Bypass Branch
    router >> Edge(color="red", label="EMERGENCY") >> emergency >> twilio_api
    router >> Edge(color="orange", label="LOCATOR") >> locator
    
    # Parallel Therapy Branch
    router >> Edge(color="blue", label="THERAPY") >> clinical
    router >> Edge(color="blue", label="THERAPY") >> sentiment
    
    # Synthesis
    clinical >> synthesis
    sentiment >> synthesis
    
    # Persistence & Background Tasks
    synthesis >> Edge(label="AI Response") >> gateway
    emergency >> Edge(label="AI Response") >> gateway
    locator >> Edge(label="AI Response") >> gateway
    
    gateway >> Edge(style="dashed", label="Async Mood Scoring") >> workers
    workers >> db
    gateway >> Edge(label="Save Chats") >> db
    mem >> db
    
    # Returning to user
    gateway >> ui
    gateway >> whatsapp
