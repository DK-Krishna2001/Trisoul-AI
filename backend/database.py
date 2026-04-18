from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from typing import Optional

DATABASE_URL = "sqlite:///./safespace.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class MoodLog(Base):
    __tablename__ = "mood_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    session_id = Column(String, index=True, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    mood_score = Column(Float)
    interaction_summary = Column(String)
    keywords = Column(String, default="")

    def __init__(self, user_id: str, mood_score: float, interaction_summary: str, session_id: str = None, keywords: str = "", **kwargs):
        self.user_id = user_id
        self.session_id = session_id
        self.mood_score = mood_score
        self.interaction_summary = interaction_summary
        self.keywords = keywords
        super().__init__(**kwargs)

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    session_id = Column(String, index=True)
    sender = Column(String)  # 'user' or 'ai'
    text = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    mood_score = Column(Integer, nullable=True) # Added for aggregation

    def __init__(self, user_id: str, session_id: str, sender: str, text: str, mood_score: Optional[int] = None, **kwargs):
        self.user_id = user_id
        self.session_id = session_id
        self.sender = sender
        self.text = text
        self.mood_score = mood_score
        super().__init__(**kwargs)

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    session_id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True)
    aggregated_score = Column(Integer, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    title = Column(String, nullable=True)
    
    def __init__(self, session_id: str, user_id: str, title: str = None, **kwargs):
        self.session_id = session_id
        self.user_id = user_id
        self.title = title
        super().__init__(**kwargs)

class DailySummary(Base):
    __tablename__ = "daily_summaries"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    date = Column(String) # YYYY-MM-DD
    daily_score = Column(Integer, nullable=True)
    
    def __init__(self, user_id: str, date: str, daily_score: int, **kwargs):
        self.user_id = user_id
        self.date = date
        self.daily_score = daily_score
        super().__init__(**kwargs)

class UserSummary(Base):
    __tablename__ = "user_summaries"
    user_id = Column(String, primary_key=True, index=True)
    rolling_score = Column(Integer, nullable=True)
    
    def __init__(self, user_id: str, rolling_score: int, **kwargs):
        self.user_id = user_id
        self.rolling_score = rolling_score
        super().__init__(**kwargs)

Base.metadata.create_all(bind=engine)

def save_mood(user_id: str, mood_score: float, summary: str, session_id: str = None, keywords: str = ""):
    db = SessionLocal()
    try:
        new_log = MoodLog(user_id=user_id, mood_score=mood_score, interaction_summary=summary, session_id=session_id, keywords=keywords)
        db.add(new_log)
        db.commit()
        db.refresh(new_log)
        return new_log
    finally:
        db.close()

def get_mood_history(user_id: str):
    db = SessionLocal()
    try:
        logs = db.query(MoodLog).filter(MoodLog.user_id == user_id).order_by(MoodLog.timestamp).all()
        return logs
    finally:
        db.close()

def get_session_mood_history(session_id: str):
    db = SessionLocal()
    try:
        logs = db.query(MoodLog).filter(MoodLog.session_id == session_id).order_by(MoodLog.timestamp).all()
        return logs
    finally:
        db.close()

def save_chat_message(user_id: str, session_id: str, sender: str, text: str):
    db = SessionLocal()
    try:
        # Before saving, ensure the ChatSession exists
        if not db.query(ChatSession).filter(ChatSession.session_id == session_id).first():
            new_session = ChatSession(session_id=session_id, user_id=user_id)
            db.add(new_session)
            db.commit()
            
        new_msg = ChatMessage(user_id=user_id, session_id=session_id, sender=sender, text=text)
        db.add(new_msg)
        db.commit()
        db.refresh(new_msg)
        return new_msg
    finally:
        db.close()

def get_user_sessions(user_id: str):
    """Returns a list of unique session IDs with their first message and timestamp, ordered by newest first."""
    db = SessionLocal()
    try:
        # Fetch all messages for the user ordered by timestamp descending
        all_messages = db.query(ChatMessage).filter(ChatMessage.user_id == user_id).order_by(ChatMessage.timestamp.asc()).all()
        
        # Deduplicate to keep only the first message per session
        seen_sessions = set()
        sessions = []
        for msg in all_messages:
            if msg.session_id not in seen_sessions:
                seen_sessions.add(msg.session_id)
                sessions.append(msg)
                
        # Return newest sessions first
        return sorted(sessions, key=lambda x: x.timestamp, reverse=True)
    finally:
        db.close()

def get_session_messages(session_id: str):
    """Returns all messages for a specific session ordered chronologically."""
    db = SessionLocal()
    try:
        messages = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.timestamp).all()
        return messages
    finally:
        db.close()

from datetime import timedelta

def update_aggregations_cascade(user_id: str, session_id: str, message_id: int, mood_score: int, timezone_offset_hours: int = 0):
    """
    Cascades a newly calculated mood score up the aggregation chain: Message -> Session -> Day -> User.
    """
    db = SessionLocal()
    try:
        # 0. Update the triggering message with the score
        msg = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
        if msg:
            msg.mood_score = mood_score
            db.commit()

        # 1. Recalculate ChatScore
        messages = db.query(ChatMessage).filter(ChatMessage.session_id == session_id, ChatMessage.mood_score.isnot(None)).all()
        if not messages:
            return
            
        chat_score = round(sum(m.mood_score for m in messages) / len(messages))
        
        session_row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if session_row:
            session_row.aggregated_score = chat_score
            db.commit()
            
            # 2. Recalculate DailyScore based on session start time
            user_local_start = session_row.started_at + timedelta(hours=timezone_offset_hours)
            day_str = user_local_start.date().isoformat()
            
            # Find all sessions for this user that started on the same local calendar day
            # (In a true production app we would do this via datetime manipulation in SQL)
            all_user_sessions = db.query(ChatSession).filter(ChatSession.user_id == user_id, ChatSession.aggregated_score.isnot(None)).all()
            daily_sessions = [s for s in all_user_sessions if (s.started_at + timedelta(hours=timezone_offset_hours)).date().isoformat() == day_str]
            
            if daily_sessions:
                daily_score = round(sum(s.aggregated_score for s in daily_sessions) / len(daily_sessions))
                
                daily_summary = db.query(DailySummary).filter(DailySummary.user_id == user_id, DailySummary.date == day_str).first()
                if daily_summary:
                    daily_summary.daily_score = daily_score
                else:
                    daily_summary = DailySummary(user_id=user_id, date=day_str, daily_score=daily_score)
                    db.add(daily_summary)
                db.commit()
                
                # 3. Update UserScore (Rolling 7 days)
                seven_days_ago = user_local_start.date() - timedelta(days=7)
                seven_days_str = seven_days_ago.isoformat()
                
                week_summaries = db.query(DailySummary).filter(DailySummary.user_id == user_id, DailySummary.date >= seven_days_str, DailySummary.daily_score.isnot(None)).all()
                if week_summaries:
                    user_score = round(sum(w.daily_score for w in week_summaries) / len(week_summaries))
                    user_summary = db.query(UserSummary).filter(UserSummary.user_id == user_id).first()
                    if user_summary:
                        user_summary.rolling_score = user_score
                    else:
                        user_summary = UserSummary(user_id=user_id, rolling_score=user_score)
                        db.add(user_summary)
                    db.commit()
                    
    finally:
        db.close()

def update_session_title(session_id: str, title: str):
    db = SessionLocal()
    try:
        session_row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if session_row:
            session_row.title = title
            db.commit()
    finally:
        db.close()
