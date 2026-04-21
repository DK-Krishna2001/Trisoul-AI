import os
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timezone
from typing import Optional

# Ensure that the credentials file path is correct
# We assume it is named firebase_credentials.json and placed in the backend directory
CREDENTIALS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firebase_credentials.json")

# Initialize Firebase Admin SDK if not already initialized
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        print(f"Failed to initialize Firebase Admin. Ensure {CREDENTIALS_PATH} exists and is valid. Error: {e}")

# Get a Firestore client
db = firestore.client()

# --- Firestore Collection References ---
# users/{user_id}
#   - rolling_score: int
#   - sessions/{session_id}
#       - started_at: datetime
#       - title: str
#       - aggregated_score: int
#       - messages/{message_id}
#           - sender: str ("user" or "ai")
#           - text: str
#           - mood_score: int
#           - timestamp: datetime
# mood_logs/{log_id}
#   - user_id: str
#   - session_id: str
#   - mood_score: float
#   - interaction_summary: str
#   - keywords: str
#   - timestamp: datetime

def save_mood(user_id: str, mood_score: float, summary: str, session_id: str = None, keywords: str = ""):
    """Saves a mood log to Firestore."""
    mood_log_ref = db.collection("mood_logs").document()
    mood_log_data = {
        "user_id": user_id,
        "session_id": session_id,
        "mood_score": mood_score,
        "interaction_summary": summary,
        "keywords": keywords,
        "timestamp": datetime.utcnow()
    }
    mood_log_ref.set(mood_log_data)
    # Returning a mock object that acts like the old SQLAlchemy object
    class MockMoodLog:
        pass
    mock_log = MockMoodLog()
    for k, v in mood_log_data.items():
        setattr(mock_log, k, v)
    mock_log.id = mood_log_ref.id
    return mock_log

def get_mood_history(user_id: str):
    """Retrieves all mood logs for a specific user, ordered by timestamp in memory."""
    logs_ref = db.collection("mood_logs").where("user_id", "==", user_id).stream()
    
    class MockMoodLog:
        def __init__(self, doc):
            data = doc.to_dict()
            self.id = doc.id
            self.user_id = data.get("user_id")
            self.session_id = data.get("session_id")
            self.mood_score = data.get("mood_score")
            self.interaction_summary = data.get("interaction_summary")
            self.keywords = data.get("keywords")
            self.timestamp = data.get("timestamp")
            
    logs = [MockMoodLog(log) for log in logs_ref]
    # Sort in memory by timestamp (handling aware datetimes)
    logs.sort(key=lambda x: x.timestamp if x.timestamp else datetime.min.replace(tzinfo=timezone.utc))
    return logs

def get_session_mood_history(session_id: str, user_id: Optional[str] = None):
    """Retrieves all mood logs for a specific session, optionally scoped to one user."""
    logs_ref = db.collection("mood_logs").where("session_id", "==", session_id)
    if user_id:
        logs_ref = logs_ref.where("user_id", "==", user_id)
    logs_ref = logs_ref.stream()
    
    class MockMoodLog:
        def __init__(self, doc):
            data = doc.to_dict()
            self.id = doc.id
            self.user_id = data.get("user_id")
            self.session_id = data.get("session_id")
            self.mood_score = data.get("mood_score")
            self.interaction_summary = data.get("interaction_summary")
            self.keywords = data.get("keywords")
            self.timestamp = data.get("timestamp")
            
    logs = [MockMoodLog(log) for log in logs_ref]
    # Sort in memory by timestamp (handling aware datetimes)
    logs.sort(key=lambda x: x.timestamp if x.timestamp else datetime.min.replace(tzinfo=timezone.utc))
    return logs

def save_chat_message(user_id: str, session_id: str, sender: str, text: str):
    """Saves a chat message and ensures the user and session documents exist."""
    user_ref = db.collection("users").document(user_id)
    session_ref = user_ref.collection("sessions").document(session_id)
    
    # 1. Ensure user document exists (Firestore handles this gracefully, but good for explicit tracking)
    user_doc = user_ref.get()
    if not user_doc.exists:
        user_ref.set({"rolling_score": None})
        
    # 2. Ensure session exists
    session_doc = session_ref.get()
    timestamp = datetime.utcnow()
    if not session_doc.exists:
        session_ref.set({
            "started_at": timestamp,
            "title": None,
            "aggregated_score": None
        })
        
    # 3. Add the message
    messages_ref = session_ref.collection("messages").document()
    message_data = {
        "sender": sender,
        "text": text,
        "mood_score": None,
        "timestamp": timestamp
    }
    messages_ref.set(message_data)
    
    class MockChatMessage:
        def __init__(self, msg_id, data):
            self.id = msg_id
            self.user_id = user_id
            self.session_id = session_id
            self.sender = data.get("sender")
            self.text = data.get("text")
            self.mood_score = data.get("mood_score")
            self.timestamp = data.get("timestamp")
            
    return MockChatMessage(messages_ref.id, message_data)

def get_user_sessions(user_id: str):
    """Returns a list of unique session IDs with their first message and timestamp, ordered by newest first."""
    user_ref = db.collection("users").document(user_id)
    sessions = user_ref.collection("sessions").order_by("started_at", direction=firestore.Query.DESCENDING).stream()
    
    class MockSessionSnippet:
        def __init__(self, session_id, timestamp, text, aggregated_score=None, title=None):
            self.session_id = session_id
            self.timestamp = timestamp
            self.text = text
            self.aggregated_score = aggregated_score
            self.title = title
            
    result = []
    for s_doc in sessions:
        s_data = s_doc.to_dict()
        s_id = s_doc.id
        # Get the first message for this session to extract text snippet
        messages = user_ref.collection("sessions").document(s_id).collection("messages").order_by("timestamp").limit(1).stream()
        first_msg_text = "Empty session"
        for m in messages:
            first_msg_text = m.to_dict().get("text", "")
            break
            
        result.append(MockSessionSnippet(
            session_id=s_id,
            timestamp=s_data.get("started_at"),
            text=first_msg_text,
            aggregated_score=s_data.get("aggregated_score"),
            title=s_data.get("title")
        ))
        
    return result

def get_session_messages(session_id: str, user_id: Optional[str] = None):
    """Returns all messages for a specific session ordered chronologically.
    NOTE: In Firestore schema, messages are subcollections of users -> sessions.
    Passing user_id is strongly preferred because different users may reuse the
    same session_id in testbench runs.
    """
    class MockChatMessage:
        def __init__(self, data):
            self.sender = data.get("sender")
            self.text = data.get("text")
            self.mood_score = data.get("mood_score")
            self.timestamp = data.get("timestamp")

    def read_session_messages(session_ref):
        messages = session_ref.collection("messages").order_by("timestamp").stream()
        return [MockChatMessage(m.to_dict()) for m in messages]

    if user_id:
        session_ref = db.collection("users").document(user_id).collection("sessions").document(session_id)
        if not session_ref.get().exists:
            return []
        return read_session_messages(session_ref)

    messages_result = []
    users = db.collection("users").stream()
    for u in users:
        session_ref = db.collection("users").document(u.id).collection("sessions").document(session_id)
        if session_ref.get().exists:
            messages_result = read_session_messages(session_ref)
            break # Found the session, no need to check other users
            
    return messages_result


def get_benchmark_user_chats(user_id_prefix: str = "bench_", include_empty: bool = False):
    """Returns all benchmark users and their session/message history."""
    patients = []

    for user_doc in db.collection("users").stream():
        user_id = user_doc.id
        if user_id_prefix and not user_id.startswith(user_id_prefix):
            continue

        sessions = []
        session_docs = (
            db.collection("users")
            .document(user_id)
            .collection("sessions")
            .order_by("started_at", direction=firestore.Query.ASCENDING)
            .stream()
        )

        for session_doc in session_docs:
            session_data = session_doc.to_dict()
            messages = []
            message_docs = (
                db.collection("users")
                .document(user_id)
                .collection("sessions")
                .document(session_doc.id)
                .collection("messages")
                .order_by("timestamp")
                .stream()
            )

            for message_doc in message_docs:
                message_data = message_doc.to_dict()
                messages.append({
                    "message_id": message_doc.id,
                    "sender": message_data.get("sender"),
                    "text": message_data.get("text"),
                    "mood_score": message_data.get("mood_score"),
                    "timestamp": message_data.get("timestamp"),
                })

            if include_empty or messages:
                sessions.append({
                    "session_id": session_doc.id,
                    "started_at": session_data.get("started_at"),
                    "title": session_data.get("title"),
                    "aggregated_score": session_data.get("aggregated_score"),
                    "messages": messages,
                })

        if include_empty or sessions:
            patients.append({
                "user_id": user_id,
                "rolling_score": user_doc.to_dict().get("rolling_score"),
                "session_count": len(sessions),
                "sessions": sessions,
            })

    return patients


def update_aggregations_cascade(user_id: str, session_id: str, message_id: str, mood_score: int, timezone_offset_hours: int = 0):
    """
    Cascades a newly calculated mood score up the aggregation chain.
    """
    user_ref = db.collection("users").document(user_id)
    session_ref = user_ref.collection("sessions").document(session_id)
    message_ref = session_ref.collection("messages").document(message_id)
    
    # 0. Update message
    if message_ref.get().exists:
        message_ref.update({"mood_score": mood_score})
        
    # 1. Recalculate ChatScore
    messages = session_ref.collection("messages").where("mood_score", "!=", None).stream()
    mood_scores = [m.to_dict().get("mood_score") for m in messages if isinstance(m.to_dict().get("mood_score"), (int, float))]
    
    if mood_scores:
        chat_score = round(sum(mood_scores) / len(mood_scores))
        
        session_doc = session_ref.get()
        if session_doc.exists:
            session_ref.update({"aggregated_score": chat_score})
            
            # NOTE: For Daily and Rolling 7-day averages, since we aren't using DailySummary table anymore,
            # we can calculate it dynamically directly from the sessions collection when requested,
            # or we can update a `rolling_score` on the user doc.
            # To keep it simple and faithful to the original, we will just update the user's rolling score based on recent sessions.
            
            # Find recent sessions for rolling user score (last 7 days equivalent)
            all_sessions = user_ref.collection("sessions").where("aggregated_score", "!=", None).stream()
            all_scores = [s.to_dict().get("aggregated_score") for s in all_sessions if isinstance(s.to_dict().get("aggregated_score"), (int, float))]
            if all_scores:
                user_score = round(sum(all_scores) / len(all_scores))
                user_ref.update({"rolling_score": user_score})


def update_session_title(session_id: str, title: str, user_id: Optional[str] = None):
    """Updates the title of a specific session."""
    if user_id:
        session_ref = db.collection("users").document(user_id).collection("sessions").document(session_id)
        if session_ref.get().exists:
            session_ref.update({"title": title})
        return

    users = db.collection("users").stream()
    for u in users:
        session_ref = db.collection("users").document(u.id).collection("sessions").document(session_id)
        if session_ref.get().exists:
            session_ref.update({"title": title})
            break

def get_session_title(session_id: str, user_id: Optional[str] = None) -> Optional[str]:
    """Retrieves the title of a specific session."""
    if user_id:
        session_ref = db.collection("users").document(user_id).collection("sessions").document(session_id)
        doc = session_ref.get()
        if doc.exists:
            return doc.to_dict().get("title")
        return None

    users = db.collection("users").stream()
    for u in users:
        session_ref = db.collection("users").document(u.id).collection("sessions").document(session_id)
        doc = session_ref.get()
        if doc.exists:
            return doc.to_dict().get("title")
    return None


# Helper class to mock SessionLocal for backwards compatibility in main.py where it does db = SessionLocal()
class DummyQuery:
    def __init__(self, data):
        self._data = data
    def filter(self, *args, **kwargs): return self
    def order_by(self, *args, **kwargs): return self
    def all(self): return self._data
    def first(self): return self._data[0] if self._data else None
    def outerjoin(self, *args, **kwargs): return self

class DummySession:
    def query(self, *args, **kwargs):
        # We handle specific complex queries by returning empty or mocked data
        # since main.py sometimes does direct SQLAlchemy queries.
        # This is a shim to prevent immediate crashes, but endpoints like 
        # get_global_metrics will need refactoring to use Firebase directly.
        return DummyQuery([])
    def close(self): pass
    def add(self, *args): pass
    def commit(self): pass
    def refresh(self, *args): pass

def SessionLocal():
    return DummySession()

# Mocks for model classes imported in main.py
class ChatSession: 
    session_id = None
    user_id = None
    aggregated_score = None
    title = None
    started_at = None
class MoodLog: pass
class ChatMessage: pass
class DailySummary: pass
class UserSummary: pass
