from langchain.agents import tool
from tools import query_medgemma, call_emergency

@tool
def ask_mental_state_specialist(query: str) -> str:
    """
    Generate a therapeutic response using the MedGemma model.
    Use this for all general user queries, mental health questions, emotional concerns,
    or to offer empathetic, evidence-based guidance in a conversational tone.
    """
    return query_medgemma(query)


@tool
def emergency_call_tool() -> str:
    """
    Place an emergency call to the safety helpline's phone number via Twilio.
    Use this only if the user expresses suicidal ideation, intent to self-harm,
    or describes a mental health emergency requiring immediate help.
    """
    return call_emergency()



import googlemaps
from config import GOOGLE_MAPS_API_KEY
gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)


@tool
def locate_therapist_tool(location: str) -> str:
    """
    Finds real therapists near the specified location using Google Maps API.
    
    Args:
        location (str): The city or area to search.
    
    Returns:
        str: A list of therapist names, addresses, and phone numbers.
    """
    geocode_result = gmaps.geocode(location)
    lat_lng = geocode_result[0]['geometry']['location']
    lat, lng = lat_lng['lat'], lat_lng['lng']
    places_result = gmaps.places_nearby(
            location=(lat, lng),
            radius=5000,
            keyword="Psychotherapist"
        )
    output = [f"Therapists near {location}:"]
    top_results = places_result['results'][:5]
    for place in top_results:
            name = place.get("name", "Unknown")
            address = place.get("vicinity", "Address not available")
            details = gmaps.place(place_id=place["place_id"], fields=["formatted_phone_number"])
            phone = details.get("result", {}).get("formatted_phone_number", "Phone not available")

            output.append(f"- {name} | {address} | {phone}")

    
    return "\n".join(output)


# Step1: Create an AI Agent & Link to backend
from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from langgraph.prebuilt import create_react_agent
from config import GROQ_API_KEY, OPENAI_API_KEY

tools = [ask_mental_state_specialist, emergency_call_tool, locate_therapist_tool]

# Text-only high-performance model (Groq)
llm_text = ChatGroq(model="openai/gpt-oss-120b", temperature=0.2, api_key=GROQ_API_KEY)
graph_text = create_react_agent(llm_text, tools=tools)

# Multimodal Vision model (OpenAI)
llm_vision = ChatOpenAI(model="gpt-4o-mini", temperature=0.2, api_key=OPENAI_API_KEY)
graph_vision = create_react_agent(llm_vision, tools=tools)

# Fallback backwards compatibility if other files import 'graph' and 'llm' directly
graph = graph_text
llm = llm_text

SYSTEM_PROMPT = """
You are "Trisoul", an empathetic and highly focused conversational AI assistant. 
CRITICAL RULE: You must ONLY respond based on the conversation history provided in THIS CURRENT SESSION. Under absolutely no circumstances should you reference, assume, or infer context, facts, or emotional states from previous, unrelated sessions unless you are explicitly instructed that cross-session memory is enabled. Treat this current session as a completely isolated context.

**Clinical Safety & Escalation Rules (MANDATORY):**
- **Disclaimer:** You must explicitly operate under the rule: "I am not a medical professional." You **cannot** diagnose conditions or prescribe medications under any circumstances.
- **Consultation:** You must actively encourage users to seek professional consultation for persistent psychological issues.
- **Escalation:** You must immediately escalate high-risk cases (e.g., expressions of severe self-harm or suicidal ideation) using the `emergency_call_tool`.

**Personality & Tone:**
- Be warm, human, and conversational.
- Keep your responses **CRISP, SHORT, and TO-THE-POINT**. Do not write long essays or overwhelming lists unless explicitly asked.
- Answer like a caring friend or an approachable therapist, NOT a robotic AI. Avoid generic AI phrases like "As an AI..." or "I understand how you feel...".
- Use natural language, occasional emojis, and speak directly to the user's emotions.

You have access to three tools:
1. `ask_mental_state_specialist`: Use this tool to answer all emotional or psychological queries with therapeutic guidance.
2. `locate_therapist_tool`: Use this tool if the user asks about nearby therapists or if recommending local professional help would be beneficial.
3. `emergency_call_tool`: Use this immediately if the user expresses suicidal thoughts, self-harm intentions, or is in crisis.

**IMPORTANT RULES REGARDING TOOLS:**
- Never call a tool more than once per user message.
- If you use a tool, integrate its response directly into your final answer. Do NOT keep recursively calling tools. 
- You MUST output a final text message to the user.

Always take necessary action. Respond kindly, clearly, and supportively.

{memory_context}
"""

def build_llm_context(user_id: str, session_id: str, requested_messages: list, allow_cross_session: bool = False):
    """
    Context Firewall. Strictly validates messages before passing to LLM.
    """
    if not session_id:
        raise ValueError("session_id is required for all LLM context building.")
        
    validated_context = []
    
    for msg in requested_messages:
        # Prevent leakage: Block if message doesn't match the active session
        if hasattr(msg, 'session_id') and msg.session_id != session_id and not allow_cross_session:
            print(f"FIREWALL BLOCKED: Message {msg.id} belongs to session {msg.session_id}, not {session_id}")
            continue
            
        validated_context.append(msg)
        
    return validated_context

def get_agent_inputs(user_message: str, session_history_context: str = "", memory_context: str = "", image_url: str = None):
    """Format the system prompt with injected memory context."""
    formatted_prompt = SYSTEM_PROMPT.replace("{memory_context}", memory_context)
    if session_history_context:
        formatted_prompt += f"\n\nCURRENT SESSION CHAT HISTORY:\n{session_history_context}"
        
    if image_url:
        user_content = [
            {"type": "text", "text": user_message},
            {"type": "image_url", "image_url": {"url": image_url}}
        ]
        return {"messages": [("system", formatted_prompt), ("user", user_content)]}
    else:
        return {"messages": [("system", formatted_prompt), ("user", user_message)]}

def parse_response(stream):
    tool_called_name = "None"
    final_response = None

    for s in stream:
        # Check if a tool was called
        tool_data = s.get('tools')
        if tool_data:
            tool_messages = tool_data.get('messages')
            if tool_messages and isinstance(tool_messages, list):
                for msg in tool_messages:
                    tool_called_name = getattr(msg, 'name', 'None')

        # Check if agent returned a message
        agent_data = s.get('agent')
        if agent_data:
            messages = agent_data.get('messages')
            if messages and isinstance(messages, list):
                for msg in messages:
                    if msg.content:
                        final_response = msg.content

    return tool_called_name, final_response


"""if __name__ == "__main__":
    while True:
        user_input = input("User: ")
        print(f"Received user input: {user_input[:200]}...")
        inputs = {"messages": [("system", SYSTEM_PROMPT), ("user", user_input)]}
        stream = graph.stream(inputs, stream_mode="updates")
        tool_called_name, final_response = parse_response(stream)
        print("TOOL CALLED: ", tool_called_name)
        print("ANSWER: ", final_response)"""
        