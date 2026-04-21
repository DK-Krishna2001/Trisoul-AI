# Step1: Setup FastAPI backend
from pydantic import BaseModel
import uvicorn
import sys
import os

# Add backend directory to sys.path to allow imports like `ai_agent`, `memory`, etc.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ai_agent import graph, SYSTEM_PROMPT, parse_response, get_agent_inputs, llm
from memory import get_relevant_history, save_interaction
from firebase_db import (
    save_mood, get_mood_history, get_session_mood_history, save_chat_message, 
    get_user_sessions, get_session_messages, update_aggregations_cascade, 
    get_session_title, update_session_title, get_benchmark_user_chats
)
from fastapi import FastAPI, Form, BackgroundTasks, UploadFile, File, HTTPException
import re
from config import GROQ_API_KEY, OPENAI_API_KEY, TESTBENCH_PASSWORD
from langchain_groq import ChatGroq
import tempfile
from openai import OpenAI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=OPENAI_API_KEY)

@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """Receives an audio file, saves it temporarily, and calls OpenAI Whisper to transcribe."""
    try:
        # Create a temporary file to save the uploaded audio
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav", mode="wb") as temp_audio:
            content = await file.read()
            temp_audio.write(content)
            temp_audio_path = temp_audio.name

        # Transcribe with Whisper
        with open(temp_audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )

        # Clean up
        os.remove(temp_audio_path)
        return {"text": transcript.text}
    except Exception as e:
        return {"error": str(e)}

# Background task to evaluate mood using a quick LLM call
def evaluate_and_save_mood(user_id: str, session_id: str, user_message_id: int, user_message: str, ai_response: str):
    evaluator_llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.0, api_key=GROQ_API_KEY)
    prompt = f"""
    Analyze the following user's message and the AI's response. 
    Rate the user's current mood on a scale of 1 to 10, where 1 = extremely distressed/depressed/anxious, and 10 = extremely happy/calm/positive.
    Also, identify 1-3 highly prominent trigger words or central themes (nouns/adjectives) from the user's message that drove this sentiment (e.g. "breakup, sleep, stress" or "vacation, family").
    
    User: {user_message}
    AI: {ai_response}
    
    Output ONLY a JSON format like this: {{"score": 5, "summary": "User is feeling anxious about work.", "keywords": "stress, work, anxiety"}}
    """
    try:
        result = evaluator_llm.invoke(prompt)
        # Simple extraction
        content = result.content
        import json
        import re
        match = re.search(r'\{.*\}', content.replace('\n', ''))
        if match:
            data = json.loads(match.group(0))
            score = float(data.get("score", 5))
            summary = data.get("summary", "No summary")
            keywords = data.get("keywords", "")
            save_mood(user_id=user_id, mood_score=score, summary=summary, session_id=session_id, keywords=keywords)
            
            # Trigger cascade for integer score
            int_score = int(round(score))
            update_aggregations_cascade(user_id=user_id, session_id=session_id, message_id=user_message_id, mood_score=int_score)
            
    except Exception as e:
        print(f"Error evaluating mood: {e}")

# Background task to generate a neutral title for the session
def generate_and_save_title(user_id: str, session_id: str):
    existing_title = get_session_title(session_id, user_id=user_id)
    if existing_title:
        return  # Already has a title
        
    messages = get_session_messages(session_id, user_id=user_id)
    if not messages: return
    
    # Take up to 3 user messages for context to generate title
    user_messages = []
    for m in messages:
        if m.sender == "user":
            user_messages.append(m.text)
            if len(user_messages) >= 3:
                break
    
    if not user_messages: return
    conversation_text = "\n".join(user_messages)
    
    evaluator_llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.2, api_key=GROQ_API_KEY)
    prompt = f"""
    Generate a neutral, highly descriptive, 3-to-7 word title summarizing the core topic or intent of the following conversation.
    CRITICAL RULES:
    - The title MUST be entirely neutral and objective (e.g., "Exam anxiety coping plan", "Visa biometrics scheduling").
    - You are FORBIDDEN from using strong emotion-only phrases, clinical terms, or distress signals. DO NOT use words like "Sad", "Depressed", "Heartbreak", "Help", "Bad day", "Lonely", etc.
    - If the topic is unclear or too short to deduce, fallback exactly to: "General questions and guidance".
    Output ONLY the raw title text. Do not use quotes or prefixes.
    
    Conversation:
    {conversation_text}
    """
    try:
        result = evaluator_llm.invoke(prompt)
        title = result.content.strip().strip('"').strip("'")
        update_session_title(session_id, title, user_id=user_id)
    except Exception as e:
        print(f"Error generating title: {e}")

# Step2: Receive and validate request from Frontend
class Query(BaseModel):
    message: str
    user_id: str = "default_user"  # Added user_id for memory tracking
    session_id: str = "default_session" # Added session matching
    attachment_type: str = None  # "image" or "document"
    attachment_data: str = None  # Base64 string of the file
    attachment_name: str = None  # Original filename


class TestbenchLogin(BaseModel):
    user_id: str
    password: str


class TherapistBenchmarkAccess(BaseModel):
    password: str
    user_id_prefix: str = "bench_"
    include_empty: bool = False


from fastapi.responses import StreamingResponse
import json

@app.post("/testbench/login")
def testbench_login(login: TestbenchLogin):
    if login.password != TESTBENCH_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid benchmark password")

    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", login.user_id):
        raise HTTPException(
            status_code=400,
            detail="Benchmark user_id may only contain letters, numbers, underscore, dash, dot, or colon.",
        )

    return {"user_id": login.user_id, "mode": "testbench"}

@app.post("/testbench/therapist/chats")
def get_testbench_chats_for_therapist(access: TherapistBenchmarkAccess):
    if access.password != TESTBENCH_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid benchmark password")

    if access.user_id_prefix and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", access.user_id_prefix):
        raise HTTPException(
            status_code=400,
            detail="user_id_prefix may only contain letters, numbers, underscore, dash, dot, or colon.",
        )

    patients = get_benchmark_user_chats(
        user_id_prefix=access.user_id_prefix,
        include_empty=access.include_empty,
    )

    return {
        "mode": "testbench_therapist_read",
        "user_id_prefix": access.user_id_prefix,
        "patient_count": len(patients),
        "patients": patients,
    }

@app.post("/ask")
def ask(query: Query, background_tasks: BackgroundTasks):
    from ai_agent import graph
    
    # Handle Attachments
    attachment_context = ""
    image_url = None
    
    if query.attachment_type and query.attachment_data:
        if query.attachment_type == "document":
            import base64
            import fitz  # PyMuPDF
            import tempfile
            import os
            try:
                # Decode base64 to temp file
                b64_data = query.attachment_data.split(",")[-1] if "," in query.attachment_data else query.attachment_data
                file_bytes = base64.b64decode(b64_data)
                
                if query.attachment_name and query.attachment_name.lower().endswith('.txt'):
                    extracted_text = file_bytes.decode('utf-8', errors='ignore')
                else:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(file_bytes)
                        tmp_path = tmp.name
                        
                    doc = fitz.open(tmp_path)
                    extracted_text = ""
                    for page in doc:
                        extracted_text += page.get_text() + "\n"
                    doc.close()
                    os.remove(tmp_path)
                
                attachment_context = f"\n\n[USER ATTACHED DIRECT DOCUMENT CONTEXT: '{query.attachment_name}']\n{extracted_text.strip()}"
                
            except Exception as e:
                print(f"Error parsing document: {e}")
                attachment_context = f"\n\n[User tried to attach a document named '{query.attachment_name}', but it couldn't be read.]"
                
        elif query.attachment_type == "image":
            image_url = query.attachment_data
            attachment_context = f"\n\n[User attached an image.]"
    
    # Save user message to chat history immediately
    saved_text = query.message
    if query.attachment_name:
        saved_text += f"\n[Attached File: {query.attachment_name}]"
        
    user_msg_db = save_chat_message(user_id=query.user_id, session_id=query.session_id, sender="user", text=saved_text)
    user_message_id = user_msg_db.id
    
    # Fetch memory context
    combined_message = query.message + attachment_context
    memory_context = get_relevant_history(user_id=query.user_id, session_id=query.session_id, current_query=combined_message)
    inputs = get_agent_inputs(user_message=combined_message, memory_context=memory_context, image_url=image_url)
    
    stream = graph.stream(inputs, stream_mode="updates")
        
    tool_called_name, final_response = parse_response(stream)
    
    # Save interaction to DB
    if final_response:
         save_interaction(user_id=query.user_id, session_id=query.session_id, user_message=query.message, ai_response=final_response)
         
         # Save AI message to chat history
         save_chat_message(user_id=query.user_id, session_id=query.session_id, sender="ai", text=final_response)
         
         # Trigger background mood evaluation and aggregation cascade
         background_tasks.add_task(evaluate_and_save_mood, query.user_id, query.session_id, user_message_id, query.message, final_response)
         background_tasks.add_task(generate_and_save_title, query.user_id, query.session_id)
         
         return {
             "response": final_response,
             "tool_called": tool_called_name,
             "user_id": query.user_id,
             "session_id": query.session_id,
         }
    else:
         return {
             "response": "I'm sorry, I couldn't generate a response.",
             "tool_called": "None",
             "user_id": query.user_id,
             "session_id": query.session_id,
         }

@app.post("/testbench/ask")
def testbench_ask(query: Query, background_tasks: BackgroundTasks):
    """Unauthenticated benchmark endpoint with the same behavior as /ask."""
    return ask(query=query, background_tasks=background_tasks)

@app.get("/mood_history/{user_id}")
def get_mood(user_id: str):
    try:
        # Use get_mood_history from firebase_db
        results = get_mood_history(user_id)
        
        return [
            {
                "timestamp": log.timestamp, 
                "score": log.mood_score, 
                "summary": log.interaction_summary,
                "keywords": log.keywords
            } 
            for log in results
        ]
    except Exception as e:
        print(f"Error in get_mood: {e}")
        return []

@app.get("/session_mood/{session_id}")
def get_session_mood(session_id: str):
    history = get_session_mood_history(session_id=session_id)
    return [{"timestamp": log.timestamp, "score": log.mood_score, "summary": log.interaction_summary} for log in history]

@app.get("/users/{user_id}/sessions/{session_id}/mood")
def get_user_session_mood(user_id: str, session_id: str):
    history = get_session_mood_history(session_id=session_id, user_id=user_id)
    return [{"timestamp": log.timestamp, "score": log.mood_score, "summary": log.interaction_summary} for log in history]

@app.get("/sessions/{user_id}")
def get_sessions_route(user_id: str):
    sessions = get_user_sessions(user_id)
    result = []
    for s in sessions:
        result.append({
            "session_id": s.session_id,
            "first_message": s.title if s.title else s.text,
            "timestamp": s.timestamp,
            "aggregated_score": s.aggregated_score
        })
    return result

@app.get("/global_metrics/{user_id}")
def get_global_metrics(user_id: str):
    try:
        # Get sessions from Firestore
        all_sessions = get_user_sessions(user_id)
        # Filter sessions that have an aggregated score
        sessions = [s for s in all_sessions if s.aggregated_score is not None]
        # Sort by timestamp ascending for trend calculation
        sessions.sort(key=lambda x: x.timestamp)
        
        if not sessions:
            return {"total_sessions": 0, "lifetime_average": 0, "trend": "No Data", "highest_session": None, "lowest_session": None}
            
        total_sessions = len(sessions)
        lifetime_average = round(sum(s.aggregated_score for s in sessions) / total_sessions, 1)
        
        # Calculate Trend
        trend = "Stable \u2192"
        if total_sessions >= 3:
            recent_avg = sum(s.aggregated_score for s in sessions[-3:]) / 3
            if recent_avg - lifetime_average > 0.5:
                trend = "Trending Up \u2197"
            elif lifetime_average - recent_avg > 0.5:
                trend = "Trending Down \u2198"
                
        # Calculate Extremes
        highest_s = max(sessions, key=lambda x: x.aggregated_score)
        lowest_s = min(sessions, key=lambda x: x.aggregated_score)

        # Calculate top themes with dynamic percentage weights
        from datetime import datetime, timezone
        themes_raw_scores = {}
        total_weight = 0.0
        # Use get_mood_history from firebase_db
        logs = get_mood_history(user_id)
        now = datetime.now(timezone.utc)
        
        for log in logs:
            if log.keywords:
                # Calculate Recency Decay (0.9 per day)
                days_ago = (now - log.timestamp).days if log.timestamp else 0
                decay_factor = 0.9 ** max(0, days_ago)
                
                # Calculate Emotional Intensity (farther from 5 = higher weight)
                intensity_multiplier = 1.0 + (abs((log.mood_score or 5.0) - 5.0) / 5.0)
                
                # Base weight for an individual mention
                mention_weight = 1.0 * decay_factor * intensity_multiplier
                
                for word in log.keywords.split(","):
                    w = word.strip().lower()
                    if w and w not in ["no summary", "none"]:
                        themes_raw_scores[w] = themes_raw_scores.get(w, 0.0) + mention_weight
                        total_weight += mention_weight
                        
        # Sort and convert to exact percentages
        sorted_themes = sorted(themes_raw_scores.items(), key=lambda item: item[1], reverse=True)
        top_themes = []
        for theme, weight in sorted_themes[:5]:
            percentage = round((weight / total_weight) * 100) if total_weight > 0 else 0
            top_themes.append({"theme": theme, "percentage": percentage})

        return {
            "total_sessions": total_sessions,
            "lifetime_average": lifetime_average,
            "trend": trend,
            "highest_session": {"score": highest_s.aggregated_score, "title": highest_s.title or "General chat"},
            "lowest_session": {"score": lowest_s.aggregated_score, "title": lowest_s.title or "General chat"},
            "top_themes": top_themes
        }
    except Exception as e:
        print(f"Error in get_global_metrics: {e}")
        return {"total_sessions": 0, "lifetime_average": 0, "trend": "Error", "highest_session": None, "lowest_session": None}

@app.get("/generate_ai_checkin/{user_id}")
def generate_ai_checkin(user_id: str):
    metrics = get_global_metrics(user_id)
    if not metrics or metrics.get("total_sessions", 0) == 0:
        return {"reflection": "You haven't completed any therapy sessions yet! Whenever you're ready to start, I'll be here to track your progress and reflect on your journey together."}

    prompt = f"""You are 'Trisoul', an empathetic AI Therapist.

Generate a warm, supportive 'Weekly Check-in' reflection for the user based on their overall emotional data:
- Lifetime Average Mood: {metrics['lifetime_average']}/10
- Recent Trend: {metrics['trend']}
- Highest Point: {metrics['highest_session']['score']}/10 (Topic: {metrics['highest_session']['title']})
- Lowest Point: {metrics['lowest_session']['score']}/10 (Topic: {metrics['lowest_session']['title']})

Write 1-2 short, encouraging paragraphs. Acknowledge their highs and lows, comment on their trend, and ask a gentle, open-ended question about how they are feeling right now. Start by addressing them warmly. Do not sound robotic or use lists. Output only the message markdown.
"""
    try:
        response = llm.invoke(prompt)
        return {"reflection": response.content}
    except Exception as e:
        print(f"Error generating check-in: {e}")
        return {"reflection": "I'm having a little trouble gathering your thoughts right now, but your progress is securely saved. Let's chat more to keep building your emotional journey!"}

@app.get("/session/{session_id}")
def get_session_route(session_id: str):
    messages = get_session_messages(session_id)
    return [{"sender": m.sender, "text": m.text, "timestamp": m.timestamp} for m in messages]

@app.get("/users/{user_id}/sessions/{session_id}/messages")
def get_user_session_route(user_id: str, session_id: str):
    messages = get_session_messages(session_id, user_id=user_id)
    return [{"sender": m.sender, "text": m.text, "timestamp": m.timestamp} for m in messages]

@app.get("/generate_clinical_report/{user_id}")
def generate_clinical_report(user_id: str):
    metrics = get_global_metrics(user_id)
    if not metrics or metrics.get("total_sessions", 0) == 0:
        return {"report": "Insufficient data to generate a clinical analysis report. Please complete at least one therapy session."}

    themes_str = ", ".join([f"{t['theme']} ({t['percentage']}%)" for t in metrics.get('top_themes', [])])
    
    prompt = f"""You are an Expert Clinical Assessor reviewing a patient's chart.

Generate a formal, strictly organized clinical analysis report based on the following patient metrics:
- Total Sessions: {metrics['total_sessions']}
- Lifetime Average Mood: {metrics['lifetime_average']}/10
- Recent Trend: {metrics['trend']}
- Highest Session Point: {metrics['highest_session']['score']}/10 (Context: {metrics['highest_session']['title']})
- Lowest Session Point: {metrics['lowest_session']['score']}/10 (Context: {metrics['lowest_session']['title']})
- Core Identified Themes & Impact: {themes_str}

Format the output in clean, professional Markdown. 
Do not use conversational language or introductory greetings. 
Structure the report exactly like this:
### Executive Summary
(1 short paragraph summarizing overall state and trend)

### Thematic Analysis
(1 bullet point for each of the Core Identified Themes explaining how its percentage weight indicates its relative impact on the patient's emotional state)

### Clinical Recommendations
(2-3 actionable, professional recommendations for the patient based on their lowest points and dominant themes)
"""
    try:
        response = llm.invoke(prompt)
        return {"report": response.content}
    except Exception as e:
        print(f"Error generating clinical report: {e}")
        return {"report": "An error occurred while generating the clinical report. Please try again later."}


from fastapi.responses import PlainTextResponse
from xml.etree.ElementTree import Element, tostring

def _twiml_message(body: str) -> PlainTextResponse:
    """Create minimal TwiML <Response><Message>...</Message></Response>"""
    response_el = Element('Response')
    message_el = Element('Message')
    message_el.text = body
    response_el.append(message_el)
    xml_bytes = tostring(response_el, encoding='utf-8')
    return PlainTextResponse(content=xml_bytes, media_type='application/xml')



@app.post("/whatsapp_ask")
async def whatsapp_ask(Body: str = Form(...)): 
    user_text = Body.strip() if Body else ""
    inputs = {"messages": [("system", SYSTEM_PROMPT), ("user", user_text)]}
    stream = graph.stream(inputs, stream_mode="updates")
    tool_called_name, final_response = parse_response(stream)    

    if not final_response:
        final_response = "I'm here to support you, but I couldn't generate a response just now."

    # Step3: Send response to Twilio
    return _twiml_message(final_response)



if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)


