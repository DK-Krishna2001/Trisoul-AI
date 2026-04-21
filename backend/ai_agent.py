import json
import googlemaps
import time
from typing import TypedDict, Annotated, Sequence, Any
import operator
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain.agents import tool

from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from groq import RateLimitError
from config import GROQ_API_KEY, OPENAI_API_KEY, GOOGLE_MAPS_API_KEY
from tools import query_clinical, call_emergency
from langgraph.prebuilt import create_react_agent

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

# ==========================================
# 1. Models Initialization
# ==========================================
# Fast router/sentiment models 
llm_fast = ChatGroq(model="llama-3.1-8b-instant", temperature=0.0, api_key=GROQ_API_KEY) 
# Synthesis Model
llm_text = ChatGroq(model="openai/gpt-oss-120b", temperature=0.2, api_key=GROQ_API_KEY) 

# ==========================================
# 2. State Definition for Custom Parallel Graph
# ==========================================
class AgentState(TypedDict):
    user_message: str
    memory_context: str
    clinical_insight: str
    emotional_tone: dict
    tool_called: str
    final_response: str
    intent: str
    image_url: str


# ==========================================
# 3. Node Definitions
# ==========================================

def router_node(state: AgentState):
    """Extremely fast zero-shot intent classifier."""
    user_msg = state.get("user_message", "")
    
    prompt = f"""
    Analyze the user's message and determine the INTENT.
    Output ONLY a valid JSON object with a single key "intent_type".
    
    Options for "intent_type":
    1. "EMERGENCY" - user expresses severe self-harm, suicidal ideation, or crisis.
    2. "LOCATE_THERAPIST" - user asks to find a clinic, therapist, psychiatric hospital, or professional help near a location.
    3. "THERAPY" - for general chat, feelings, emotion, anxiety, sadness, routine therapy.
    
    User Message: "{user_msg}"
    """
    
    try:
        response = llm_fast.invoke([SystemMessage(content=prompt)])
        content = response.content.strip()
        # Clean markdown if present
        if content.startswith("```json"):
            content = content[7:-3]
        elif content.startswith("```"):
            content = content[3:-3]
            
        data = json.loads(content)
        intent = data.get("intent_type", "THERAPY")
    except Exception as e:
        print(f"Router fast-fail, defaulting to THERAPY: {e}")
        intent = "THERAPY"
        
    return {"intent": intent}


def emergency_tool_node(state: AgentState):
    """Directly triggers Twilio emergency call."""
    call_emergency()
    return {
        "tool_called": "emergency_call_tool",
        "final_response": "I hear how much pain you are in right now. I have triggered the emergency protocol. Please stay safe, help is on the way. You can also call the National Suicide Prevention Lifeline at 988 immediately."
    }


def locate_therapist_node(state: AgentState):
    """Directly queries Google Maps API for therapists."""
    user_msg = state.get("user_message", "")
    
    # Fast geography extraction
    prompt = "Extract the city, state, or location from this message. Output ONLY the location name and nothing else."
    res = llm_fast.invoke([SystemMessage(content=prompt), HumanMessage(content=user_msg)])
    location = res.content.strip()
    
    if not location or len(location) > 30: 
        location = "New York" # Fallback
    
    try:
        geocode_result = gmaps.geocode(location)
        if geocode_result:
            lat_lng = geocode_result[0]['geometry']['location']
            lat, lng = lat_lng['lat'], lat_lng['lng']
            places_result = gmaps.places_nearby(
                location=(lat, lng),
                radius=5000,
                keyword="Psychotherapist"
            )
            output = [f"Here are some highly-rated professionals near {location}:"]
            for place in places_result.get('results', [])[:5]:
                name = place.get("name", "Unknown")
                address = place.get("vicinity", "")
                output.append(f"- {name} | {address}")
            result = "\n".join(output)
        else:
            result = f"I couldn't find exact location data for '{location}' right now."
    except Exception as e:
        print(f"Location error: {e}")
        result = "I'm having trouble looking up the maps right now."

    return {
        "tool_called": "locate_therapist_tool",
        "final_response": f"{result}\n\nWould you like to talk more about how you're feeling right now?"
    }


def clinical_node(state: AgentState):
    """Hits the Clinical LLM for therapy insight."""
    user_msg = state.get("user_message", "")
    image_url = state.get("image_url", None)
    insight = query_clinical(user_msg, image_url)
    return {"clinical_insight": insight}


def sentiment_node(state: AgentState):
    """Fast secondary evaluation of emotional tone."""
    user_msg = state.get("user_message", "")
    prompt = f"""
    Analyze the user's message.
    Output ONLY a JSON format exactly like this:
    {{"primary_emotion": "Anxious", "mood_score": 3, "risk_of_harm": false, "context": "User is overwhelmed."}}
    
    User: {user_msg}
    """
    try:
        res = llm_fast.invoke([SystemMessage(content=prompt)])
        content = res.content.strip()
        if content.startswith("```json"): content = content[7:-3]
        elif content.startswith("```"): content = content[3:-3]
        data = json.loads(content)
        return {"emotional_tone": data}
    except Exception:
        return {"emotional_tone": {"primary_emotion": "Unknown", "mood_score": 5, "risk_of_harm": False, "context": "Error Parsing"}}


def synthesis_node(state: AgentState):
    """Primary LLM combines MedGemma insight, User Tone, and Memory to write the final perfect message."""
    user_msg = state.get("user_message", "")
    clinical_insight = state.get("clinical_insight", "")
    emotional_tone = state.get("emotional_tone", {})
    memory_context = state.get("memory_context", "")
    
    sys_prompt = f"""
    You are "Trisoul", an empathetic and highly focused conversational AI psychological assistant. 
    You act as the main voice synthesizer. Follow these strict rules:
    
    1. Respond like a caring friend or an approachable therapist, NOT a robotic AI. Use natural language. 
    2. Keep responses CRISP and short.
    3. Never use generic AI phrases like "As an AI...".
    4. CRITICAL: If the user attached an image, DO NOT apologize for not being able to see it. The image has ALREADY been analyzed by your Vision Engine. You MUST trust the "Clinical Insight" below as the exact description of the image. Base your entire response on that insight as if you saw the image yourself!
    
    ====== REQUIRED CONTEXT TO SYNTHESIZE ======
    
    1. Clinical Insight from Clinical Therapist Engine:
    "{clinical_insight}"
    
    2. Sentiment Analysis of the user's latest message:
    Emotion: {emotional_tone.get('primary_emotion')}
    Mood Score (1-10): {emotional_tone.get('mood_score')}
    
    3. User Memory Context:
    {memory_context}
    
    Synthesize all this information to formulate the final, perfectly empathetic response directly to the user. Do not explain your step by step logic, just act as Trisoul.
    """
    
    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=user_msg)
    ]

    for attempt in range(2):
        try:
            res = llm_text.invoke(messages)
            return {"final_response": res.content, "tool_called": "ask_mental_state_specialist"}
        except RateLimitError as e:
            print(f"Synthesis rate-limited on attempt {attempt + 1}: {e}")
            if attempt == 0:
                time.sleep(6)
                continue
        except Exception as e:
            print(f"Synthesis failed: {e}")
            break

    return {
        "final_response": "I'm here with you. I am having a little trouble generating the full response right now, but what you shared matters. Try taking one slow breath and tell me the part that feels heaviest in this moment.",
        "tool_called": "synthesis_fallback"
    }


# ==========================================
# 4. Routing Edges
# ==========================================
def route_initial(state: AgentState):
    intent = state.get("intent", "THERAPY")
    if intent == "EMERGENCY":
        return "emergency_tool"
    elif intent == "LOCATE_THERAPIST":
        return "locate_therapist_tool"
    else:
        return ["clinical", "sentiment"] # Fan-out to parallel branch!


# ==========================================
# 5. Graph Assembly
# ==========================================
builder = StateGraph(AgentState)

# Add Nodes
builder.add_node("router", router_node)
builder.add_node("emergency_tool", emergency_tool_node)
builder.add_node("locate_therapist_tool", locate_therapist_node)
builder.add_node("clinical", clinical_node)
builder.add_node("sentiment", sentiment_node)
builder.add_node("synthesis", synthesis_node)

# Tie them together
builder.add_edge(START, "router")
builder.add_conditional_edges("router", route_initial)
builder.add_edge("emergency_tool", END)
builder.add_edge("locate_therapist_tool", END)

# Parallel converge
builder.add_edge("clinical", "synthesis")
builder.add_edge("sentiment", "synthesis")
builder.add_edge("synthesis", END)

graph_text = builder.compile()
graph = graph_text # Fallback for old imports


# ==========================================
# 7. Helper Functions
# ==========================================
def get_agent_inputs(user_message: str, session_history_context: str = "", memory_context: str = "", image_url: str = None):
    # Returns inputs matching AgentState strictly
    return {
        "user_message": user_message,
        "memory_context": memory_context,
        "clinical_insight": "",
        "emotional_tone": {},
        "tool_called": "None",
        "final_response": "",
        "intent": "",
        "image_url": image_url
    }


def parse_response(stream):
    tool_called_name = "None"
    final_response = None

    for s in stream:
        if isinstance(s, dict):
            # Normal custom StateGraph update dictionary handling
            for node_name, state_update in s.items():
                if isinstance(state_update, dict):
                    if state_update.get("tool_called"):
                        tool_called_name = state_update["tool_called"]
                    if state_update.get("final_response"):
                        final_response = state_update["final_response"]
            
            # Retro-compatibility with ReAct agents for the Vision graph
            if "agent" in s:
                agent_data = s.get("agent")
                if "messages" in agent_data:
                    for msg in agent_data["messages"]:
                        if msg.content:
                            final_response = msg.content
            if "tools" in s:
                tool_data = s.get("tools")
                if "messages" in tool_data:
                    for msg in tool_data["messages"]:
                        tool_called_name = getattr(msg, 'name', 'None')
                        
    return tool_called_name, final_response

# Fallbacks for main.py generic imports
llm = llm_text
SYSTEM_PROMPT = "You are Trisoul. Answer as an empathetic therapist."
