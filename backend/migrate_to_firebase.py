import os
import sys

# Ensure backend path is in sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, ChatSession, ChatMessage, MoodLog, DailySummary, UserSummary
import firebase_db
from firebase_admin import firestore
import datetime

db = firebase_db.db

def migrate_users_and_sessions():
    """Migrates UserSummary, DailySummary, ChatSessions, and ChatMessages from SQLite to Firestore."""
    sqlite_db = SessionLocal()
    
    print("Starting migration...")
    
    try:
        # 1. Migrate Users
        print("Migrating users...")
        users = sqlite_db.query(UserSummary).all()
        for u in users:
            user_ref = db.collection("users").document(u.user_id)
            user_ref.set({
                "rolling_score": u.rolling_score
            }, merge=True)
            
        # 2. Migrate Sessions & Messages
        print("Migrating sessions and messages...")
        sessions = sqlite_db.query(ChatSession).all()
        for session in sessions:
            user_ref = db.collection("users").document(session.user_id)
            session_ref = user_ref.collection("sessions").document(session.session_id)
            
            # Ensure user doc exists even if they had no UserSummary
            user_ref.set({"_migrated": True}, merge=True)
            
            # Set Session Data
            session_ref.set({
                "started_at": session.started_at,
                "title": session.title,
                "aggregated_score": session.aggregated_score
            }, merge=True)
            
            # Migrate Messages for this session
            messages = sqlite_db.query(ChatMessage).filter(ChatMessage.session_id == session.session_id).all()
            for msg in messages:
                msg_ref = session_ref.collection("messages").document(str(msg.id)) # Use SQLite ID to avoid duplicates on re-run
                msg_ref.set({
                    "sender": msg.sender,
                    "text": msg.text,
                    "mood_score": msg.mood_score,
                    "timestamp": msg.timestamp
                }, merge=True)
                
        # 3. Migrate Mood Logs
        print("Migrating mood logs...")
        logs = sqlite_db.query(MoodLog).all()
        for log in logs:
            log_ref = db.collection("mood_logs").document(str(log.id)) # Use SQLite ID
            log_ref.set({
                "user_id": log.user_id,
                "session_id": log.session_id,
                "mood_score": log.mood_score,
                "interaction_summary": log.interaction_summary,
                "keywords": log.keywords,
                "timestamp": log.timestamp
            }, merge=True)
            
        print("Migration completed successfully!")
        
    except Exception as e:
        print(f"Error during migration: {e}")
    finally:
        sqlite_db.close()

if __name__ == "__main__":
    # WARNING: Do not run this on a production database without backing it up first!
    print("WARNING: This script will read from safespace.db and write to Firestore.")
    print("Ensure firebase_credentials.json is present and valid.")
    verify = input("Type 'yes' to proceed: ")
    if verify.lower() == 'yes':
        migrate_users_and_sessions()
    else:
        print("Migration cancelled.")
