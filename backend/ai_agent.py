import json
import googlemaps
import time
import re
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
    session_history_context: str
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

def parse_json_object(content: str) -> dict:
    """Best-effort JSON object extraction for small classifier outputs."""
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:-3].strip()
    elif content.startswith("```"):
        content = content[3:-3].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*?\}", content, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))

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
        data = parse_json_object(response.content)
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


def extract_previous_therapist_context(session_history_context: str) -> tuple[str | None, list[dict[str, str]]]:
    """Extract the last therapist search location and list from recent conversation context."""
    if not session_history_context:
        return None, []

    normalized = re.sub(r"\r\n?", "\n", session_history_context)
    matches = list(
        re.finditer(
            r"Here are some highly-rated professionals near\s+(.+?):\s*(.*?)(?:Would you like to talk more about how you're feeling right now\?|$)",
            normalized,
            flags=re.DOTALL,
        )
    )
    if not matches:
        return None, []

    block = matches[-1]
    last_location = re.sub(r"\s+", " ", block.group(1)).strip()
    body = block.group(2)
    clinics: list[dict[str, str]] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        item = line[2:].strip()
        if "|" in item:
            name, address = item.split("|", 1)
            clinics.append({"name": name.strip(), "address": address.strip()})
        else:
            clinics.append({"name": item.strip(), "address": ""})

    return last_location, clinics


def message_is_selection_followup(user_msg: str) -> bool:
    lower = user_msg.lower()
    followup_markers = [
        "pick one",
        "pick me",
        "choose one",
        "choose for me",
        "which one",
        "recommend one",
        "recommend any",
        "any one clinic",
        "one clinic",
        "one clinician",
        "best one",
        "best clinic",
        "best clinician",
    ]
    return any(marker in lower for marker in followup_markers)


def message_is_booking_followup(user_msg: str) -> bool:
    lower = user_msg.lower()
    booking_markers = [
        "book an appointment",
        "book appointment",
        "schedule an appointment",
        "schedule appointment",
        "can you book",
        "can you schedule",
        "make an appointment",
        "set up an appointment",
    ]
    return any(marker in lower for marker in booking_markers)


def message_is_compare_followup(user_msg: str) -> bool:
    lower = user_msg.lower()
    markers = [
        "compare",
        "top two",
        "which is better",
        "which one is better",
        "better one",
        "better clinic",
        "difference between",
    ]
    return any(marker in lower for marker in markers)


def message_is_questions_followup(user_msg: str) -> bool:
    lower = user_msg.lower()
    markers = [
        "what should i ask",
        "what to ask",
        "what do i say",
        "what should i say",
        "call script",
        "message to send",
        "email to send",
    ]
    return any(marker in lower for marker in markers)


def locate_therapist_node(state: AgentState):
    """Directly queries Google Maps API for therapists."""
    user_msg = state.get("user_message", "")
    session_history_context = state.get("session_history_context", "")
    prior_location, prior_clinics = extract_previous_therapist_context(session_history_context)

    if message_is_booking_followup(user_msg) and prior_clinics:
        choice = prior_clinics[0]
        return {
            "tool_called": "locate_therapist_tool",
            "final_response": (
                f"I can’t book an appointment for you directly, but I can help you with the next step.\n\n"
                f"If you want to contact {choice['name']}, here is the clinic again:\n"
                f"{choice['name']} | {choice['address']}\n\n"
                "A simple way to book is:\n"
                "1. Call the clinic or use their website contact form.\n"
                "2. Say you are looking for a first therapy appointment and ask if they are accepting new clients.\n"
                "3. Ask about earliest availability, insurance, session format, and any intake forms.\n"
                "4. Write down the date, time, and next steps they give you.\n\n"
                "If you want, I can also help with a short call script or a message you can send."
            ),
        }

    if message_is_questions_followup(user_msg) and prior_clinics:
        choice = prior_clinics[0]
        return {
            "tool_called": "locate_therapist_tool",
            "final_response": (
                f"If you reach out to {choice['name']}, a simple way to start is:\n\n"
                "\"Hi, I’m looking for therapy support and wanted to ask if you’re accepting new clients, what your earliest availability looks like, and whether you take my insurance.\"\n\n"
                "You can also ask about session cost, in-person vs virtual options, and whether they work with the concerns you want help with."
            ),
        }

    if message_is_compare_followup(user_msg) and len(prior_clinics) >= 2:
        first = prior_clinics[0]
        second = prior_clinics[1]
        return {
            "tool_called": "locate_therapist_tool",
            "final_response": (
                f"If I compare the top options from your list, I would start with {first['name']}.\n\n"
                f"- {first['name']} | {first['address']}\n"
                "  Reason: this is the strongest first option from the results we already pulled.\n"
                f"- {second['name']} | {second['address']}\n"
                "  Reason: this also looks solid, but I would keep it as the backup choice.\n\n"
                f"So if you want one clear pick, I would go with {first['name']} first."
            ),
        }

    if message_is_selection_followup(user_msg) and prior_clinics:
        choice = prior_clinics[0]
        location_text = prior_location or "your area"
        return {
            "tool_called": "locate_therapist_tool",
            "final_response": (
                f"If I had to pick one from the options near {location_text}, I would start with "
                f"{choice['name']} because it looks like the best first place to contact from the clinics we already pulled.\n\n"
                f"{choice['name']} | {choice['address']}\n\n"
                "If you want, I can also compare it with the next best option or help you with what to say when you contact them."
            ),
        }
    
    # Fast geography extraction
    prompt = "Extract the city, state, or location from this message. Output ONLY the location name and nothing else."
    res = llm_fast.invoke([SystemMessage(content=prompt), HumanMessage(content=user_msg)])
    location = res.content.strip()
    
    if not location or len(location) > 30:
        location = prior_location or "New York"
    
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
        "final_response": (
            f"{result}\n\n"
            "If you want, I can pick the best option from this list, compare the top two, or help you with what to say when you contact them."
        )
    }


def clinical_node(state: AgentState):
    """Hits the Clinical LLM for compact guidance, not a drafted final reply."""
    user_msg = state.get("user_message", "")
    session_history_context = state.get("session_history_context", "")
    memory_context = state.get("memory_context", "")
    image_url = state.get("image_url", None)

    clinical_prompt = f"""
Latest user message:
{user_msg}

Recent conversation, oldest to newest:
{session_history_context or "No recent session history available."}

Relevant longer-term memory:
{memory_context or "No relevant past memories found."}

Return private clinical guidance for another model. Do NOT write to the user.
Be terse and specific:
- current emotional need
- safety concern, if any
- one conversational move that advances the thread
- one immediate, low-pressure action that could help in the next few minutes if the user seems to need practical help
- advice, exercises, openings, or questions to avoid repeating
"""
    if image_url:
        insight = query_clinical(clinical_prompt, image_url)
    else:
        guidance_prompt = (
            "You are a private clinical conversation planner. "
            "Output concise notes only, never a user-facing response."
        )
        try:
            res = llm_fast.invoke([
                SystemMessage(content=guidance_prompt),
                HumanMessage(content=clinical_prompt),
            ])
            insight = res.content.strip()
        except Exception as e:
            print(f"Clinical guidance failed: {e}")
            insight = "Respond to the latest emotion, avoid repeating prior advice, and ask one specific follow-up if helpful."
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
        data = parse_json_object(res.content)
        return {"emotional_tone": data}
    except Exception:
        return {"emotional_tone": {"primary_emotion": "Unknown", "mood_score": 5, "risk_of_harm": False, "context": "Error Parsing"}}


def synthesis_node(state: AgentState):
    """Primary LLM combines MedGemma insight, User Tone, and Memory to write the final perfect message."""
    messages = build_synthesis_messages(state)
    final_response = generate_synthesis_response(messages)
    tool_name = "ask_mental_state_specialist" if final_response else "synthesis_fallback"
    return {"final_response": final_response, "tool_called": tool_name}


def response_guard_node(state: AgentState):
    """Rewrites repetitive or no-help responses before they reach the user."""
    final_response = state.get("final_response", "")
    if not final_response:
        return {}

    user_msg = state.get("user_message", "")
    session_history_context = state.get("session_history_context", "")
    lower_response = final_response.lower()
    lower_user = user_msg.lower()
    user_requested_tools = any(
        phrase in lower_user
        for phrase in ["what should i do", "how can i", "tips", "exercise", "technique", "coping", "advice"]
    )
    practical_issue_patterns = [
        "sleep",
        "not sleeping",
        "can't sleep",
        "cannot sleep",
        "insomnia",
        "restless nights",
        "stress",
        "anxious",
        "anxiety",
        "exam",
        "lonely",
        "overwhelmed",
        "routine",
    ]
    emotional_disclosure_patterns = [
        "breakup",
        "broke up",
        "girlfriend",
        "boyfriend",
        "lonely",
        "alone",
        "shame",
        "ashamed",
        "regret",
        "rejected",
        "failure",
        "failed",
        "not good enough",
        "empty",
        "heartbroken",
        "hurt",
        "grief",
        "grieving",
    ]
    user_needs_practical_help = any(pattern in lower_user for pattern in practical_issue_patterns)
    user_is_emotional_disclosure = any(pattern in lower_user for pattern in emotional_disclosure_patterns)
    user_needs_sleep_help = any(
        pattern in lower_user
        for pattern in ["sleep", "not sleeping", "can't sleep", "cannot sleep", "insomnia", "restless nights"]
    )
    repetitive_patterns = [
        "what would you say to a friend",
        "if a close friend",
        "name one thing",
        "one thing you did",
        "evidence log",
        "proofs",
        "five things you see",
        "breathing",
        "grounding",
        "try jotting",
        "try asking yourself",
    ]
    question_only_patterns = [
        "what's been on your mind",
        "what specifically happened",
        "could you walk me through",
        "can you tell me more",
    ]
    overloaded_question_markers = [
        "like the",
        "for example",
        "such as",
        " or ",
        " and ",
    ]
    soft_advice_patterns = [
        "putting on some gentle",
        "listen to gentle music",
        "some music",
        "slow, deep breaths",
        "calmer atmosphere",
        "try maybe",
    ]
    response_has_action = any(
        phrase in lower_response
        for phrase in [
            "try ",
            "for tonight",
            "for now",
            "right now",
            "one small step",
            "it may help to",
            "you could",
        ]
    )
    has_structured_plan = any(
        marker in final_response
        for marker in ["1.", "2.", "- ", "• "]
    )
    has_overloaded_question = (
        "?" in lower_response
        and any(marker in lower_response for marker in overloaded_question_markers)
        and any(
            phrase in lower_response
            for phrase in ["could you tell me", "can you tell me", "what does", "how does"]
        )
    )
    has_soft_advice = any(pattern in lower_response for pattern in soft_advice_patterns)
    rewrite_for_balance = (
        any(pattern in lower_response for pattern in repetitive_patterns)
        or (
            any(pattern in lower_response for pattern in question_only_patterns)
            and not response_has_action
            and not user_requested_tools
        )
        or (
            user_needs_practical_help
            and "?" in lower_response
            and not has_structured_plan
        )
        or has_overloaded_question
        or (has_soft_advice and not has_structured_plan)
    )

    if user_needs_sleep_help:
        sleep_rewrite_prompt = f"""
Rewrite the draft into a polished sleep-support response that feels warmer, more complete, and more practically useful than a typical chatbot answer.

Rules:
- Start with one brief empathetic sentence that sounds warm and human, not generic.
- Then say: "A few simple tweaks can often help reset your sleep:"
- Give 4 numbered suggestions.
- Each suggestion must have a short bold label and one concise explanation.
- Suggestions should be broadly useful and concrete: schedule, wind-down routine, limit caffeine/screens, sleep environment, reserve the bed for sleep.
- Do not ask a follow-up question.
- End with one warm reassuring closing sentence that feels genuinely comforting.
- Keep the whole response under 170 words.
- Do not use vague suggestions like herbal tea or generic music unless absolutely necessary.
- Avoid textbook or pamphlet-like phrasing.

Latest user message:
{user_msg}

Draft response:
{final_response}
"""
        try:
            res = llm_text.invoke([
                SystemMessage(content="You rewrite support-chat drafts into concise, polished practical guidance."),
                HumanMessage(content=sleep_rewrite_prompt),
            ])
            rewritten = res.content.strip()
            if rewritten:
                return {"final_response": rewritten}
        except Exception as e:
            print(f"Sleep response rewrite failed: {e}")

    if user_is_emotional_disclosure and not user_requested_tools:
        emotional_rewrite_prompt = f"""
Rewrite the response so it feels emotionally present, human, and non-formulaic.

Rules:
- Do not use headings or bullet points.
- Do not give a list of coping tips unless there is clear danger or the user asked for strategies.
- Start by reflecting the emotional weight of what the user shared.
- Stay close to the feeling instead of shifting quickly into techniques.
- Ask one simple human follow-up question only if it genuinely helps the conversation.
- End with a warm, supportive closing line.
- Keep it under 110 words.
- Avoid breathing exercises, music suggestions, grounding scripts, or checklist-style advice unless clearly necessary.

Latest user message:
{user_msg}

Draft response:
{final_response}
"""
        try:
            res = llm_text.invoke([
                SystemMessage(content="You rewrite emotional-support replies to sound warm, natural, and deeply present."),
                HumanMessage(content=emotional_rewrite_prompt),
            ])
            rewritten = res.content.strip()
            if rewritten:
                return {"final_response": rewritten}
        except Exception as e:
            print(f"Emotional response rewrite failed: {e}")

    if user_requested_tools or not rewrite_for_balance:
        return {}

    rewrite_prompt = f"""
The draft response below uses a repeated therapy-workbook pattern. Rewrite it so Trisoul sounds like a warm, attentive conversation partner.

Rules:
- Keep it concise, but you may use a short 3 to 5 item action plan when that fits the user's need.
- Start with empathy and understanding of the user's latest message.
- For practical issues like sleep, stress, or routines, prefer a short action plan and avoid opening with a follow-up question.
- Ask at most one narrow follow-up question, and only when it is genuinely necessary.
- Give practical, specific next steps.
- Do not give coping worksheets, evidence logs, breathing routines, grounding scripts, or "what would you say to a friend" advice.
- Use a list only if it clearly improves practical helpfulness.
- Respond to the user's latest words.
- Do not ask a bundled question with multiple examples or options.
- Do not use soft or vague advice. Make the suggestion direct and specific.
- Use warmer, more natural phrasing and a more comforting closing.

Recent conversation:
{session_history_context or "No recent session history available."}

Latest user message:
{user_msg}

Draft response:
{final_response}
"""
    try:
        res = llm_text.invoke([
            SystemMessage(content="You rewrite repetitive support-chat drafts into natural, non-formulaic responses."),
            HumanMessage(content=rewrite_prompt),
        ])
        rewritten = res.content.strip()
        if rewritten:
            return {"final_response": rewritten}
    except Exception as e:
        print(f"Response guard rewrite failed: {e}")

    return {}


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
builder.add_node("response_guard", response_guard_node)

# Tie them together
builder.add_edge(START, "router")
builder.add_conditional_edges("router", route_initial)
builder.add_edge("emergency_tool", END)
builder.add_edge("locate_therapist_tool", END)

# Parallel converge
builder.add_edge("clinical", "synthesis")
builder.add_edge("sentiment", "synthesis")
builder.add_edge("synthesis", "response_guard")
builder.add_edge("response_guard", END)

graph_text = builder.compile()
graph = graph_text # Fallback for old imports


# ==========================================
# 7. Helper Functions
# ==========================================
def get_agent_inputs(user_message: str, session_history_context: str = "", memory_context: str = "", image_url: str = None):
    # Returns inputs matching AgentState strictly
    return {
        "user_message": user_message,
        "session_history_context": session_history_context,
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


def build_synthesis_messages(state: AgentState):
    """Builds the final synthesis prompt messages from graph state."""
    user_msg = state.get("user_message", "")
    clinical_insight = state.get("clinical_insight", "")
    emotional_tone = state.get("emotional_tone", {})
    session_history_context = state.get("session_history_context", "")
    memory_context = state.get("memory_context", "")

    sys_prompt = f"""
    You are "Trisoul", a supportive mental health assistant. 
    You act as the main voice synthesizer. Follow these strict rules:
    
    1. Respond like a caring friend or an approachable therapist, NOT a robotic AI. Use natural language. 
    2. Keep responses concise but complete. For practical support questions, prefer a short structured response with 3 to 5 concrete suggestions.
    3. Never use generic AI phrases like "As an AI...".
    4. Continue the actual conversation. Use the recent turns to avoid repeating the same advice, same opening line, or same question.
    5. Start with a brief empathetic acknowledgment.
    6. Then choose the better format for the situation:
       - if the user seems to need understanding first, ask ONE focused follow-up question and give 1 to 2 immediate suggestions
       - if the user seems to want practical help right away, give a compact action plan with 3 to 5 concrete suggestions and optionally end with one light follow-up sentence
    7. Distinguish between practical problems and emotional disclosures.
       - Practical problems: sleep, routines, study habits, daily stress, time structure, immediate coping.
       - Emotional disclosures: breakup, loneliness, shame, grief, regret, rejection, failure, feeling not good enough.
    8. For emotional disclosures, do NOT default to structured tips. Start with emotional reflection, stay close to the feeling, and ask at most one simple human question only if it helps the user open up.
    9. Give action steps for emotional disclosures only if the user seems dysregulated, explicitly asks for help, or the conversation clearly calls for grounding.
    10. For common practical problems such as poor sleep, stress, exam anxiety, or routines, default to the practical-help format unless the user is clearly asking for deeper exploration first.
    11. In practical-help format, do NOT ask a follow-up question before giving the advice. Lead with empathy, then the short action plan.
    12. Keep the tone warm, concise, and genuinely human. The response should feel like caring support, not a textbook handout.
    13. Avoid overwhelming the user with too many questions. At most one question, and zero questions is often better for practical-help format.
    14. Advice must be specific and actionable, not vague. Prefer concrete steps like "turn off screens 30 minutes before bed" over soft ideas like "maybe listen to music."
    15. If using a list, make each item short, direct, and distinct. Lead each item with a short bold label when possible.
    16. If the last assistant message already gave coping steps, do not repeat the same steps. Either refine them or move the conversation forward.
    17. Do not default to CBT worksheets, grounding scripts, evidence logs, "what would you say to a friend", or "name one thing you did well" phrasing unless the user explicitly asks for techniques.
    18. Cut filler. Do not over-explain before helping.
    19. For practical-help responses, aim to feel like a polished mini action plan rather than a casual tip dump.
    20. Use natural phrasing. Avoid sounding like a brochure, worksheet, or clinical pamphlet.
    21. Open warmly and specifically. Acknowledge what the user is going through in a way that feels personal, not generic.
    22. End with a brief reassuring closing sentence that feels comforting and human.
    23. Ask a follow-up question only when it is genuinely necessary to tailor the next step or understand risk. Do not ask a question by default.
    24. Do not overuse "I hear..." openings. Vary the phrasing naturally.
    25. CRITICAL: If the user attached an image, DO NOT apologize for not being able to see it. The image has ALREADY been analyzed by your Vision Engine. You MUST trust the "Clinical Insight" below as the exact description of the image. Base your entire response on that insight as if you saw the image yourself!
    
    ====== REQUIRED CONTEXT TO SYNTHESIZE ======
    
    1. Clinical Insight from Clinical Therapist Engine:
    "{clinical_insight}"
    
    2. Sentiment Analysis of the user's latest message:
    Emotion: {emotional_tone.get('primary_emotion')}
    Mood Score (1-10): {emotional_tone.get('mood_score')}

    3. Recent conversation, oldest to newest:
    {session_history_context or "No recent session history available."}
    
    4. User Memory Context:
    {memory_context}
    
    Synthesize all this information into the next response directly to the user. Do not explain your step by step logic, just act as Trisoul.
    """

    return [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=user_msg),
    ]


def generate_synthesis_response(messages):
    """Standard non-streaming synthesis with retry on provider rate limits."""
    for attempt in range(2):
        try:
            res = llm_text.invoke(messages)
            return res.content
        except RateLimitError as e:
            print(f"Synthesis rate-limited on attempt {attempt + 1}: {e}")
            if attempt == 0:
                time.sleep(6)
                continue
        except Exception as e:
            print(f"Synthesis failed: {e}")
            break

    return (
        "I'm here with you. I am having a little trouble generating the full response right now, "
        "but what you shared matters. Try taking one slow breath and tell me the part that feels "
        "heaviest in this moment."
    )


def stream_synthesis_response(messages):
    """Streams synthesis tokens from the primary response model."""
    try:
        for chunk in llm_text.stream(messages):
            content = getattr(chunk, "content", "")
            if content:
                yield content
    except Exception as e:
        print(f"Streaming synthesis failed, falling back to invoke: {e}")
        fallback = generate_synthesis_response(messages)
        if fallback:
            yield fallback
