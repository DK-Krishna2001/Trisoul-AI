# Step1: Setup Cloud Groq & OpenAI APIs with Persona
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from config import GROQ_API_KEY, OPENAI_API_KEY

def query_clinical(prompt: str, image_url: str = None) -> str:
    """
    Calls the Cloud LLM with a therapist personality profile.
    Dynamically swaps to gpt-4o-mini if image is attached.
    """
    system_prompt = """You are Dr. Emily Hartman, a warm and experienced clinical psychologist. 
    Respond to patients with:

    1. Emotional attunement ("I can sense how difficult this must be...")
    2. Gentle normalization ("Many people feel this way when...")
    3. Practical guidance ("What sometimes helps is...")
    4. Strengths-focused support ("I notice how you're...")

    Key principles:
    - Never use brackets or labels
    - Blend elements seamlessly
    - Vary sentence structure
    - Use natural transitions
    - Mirror the user's language level
    - Keep the conversation moving in the way that best fits the latest turn: reflect, summarize, suggest one small next step, or ask one open-ended question when it would genuinely help
    - Avoid repeating coping advice, openings, or questions that were already used in the recent conversation
    - NEVER diagnose the user with a clinical disorder. Act strictly as supportive care.
    - Proactively connect patterns from the user's past memory contexts to their current feelings.
    """
    
    try:
        if image_url:
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7, api_key=OPENAI_API_KEY)
            human_msg = HumanMessage(content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}}
            ])
            response = llm.invoke([SystemMessage(content=system_prompt), human_msg])
        else:
            llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.7, api_key=GROQ_API_KEY)
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt)
            ])
            
        return response.content.strip()
    except Exception as e:
        print(f"\n[CRITICAL ERROR in query_clinical]: {e}\n")
        return f"I'm having technical difficulties, but I want you to know your feelings matter. Please try again shortly."


# Step2: Setup Twilio calling API tool
from twilio.rest import Client
from config import TWILLIO_ACCOUNT_KK, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, EMERGENCY_CONTACT

def call_emergency():
    try:
        client = Client(TWILLIO_ACCOUNT_KK, TWILIO_AUTH_TOKEN)
        call = client.calls.create(
            to=EMERGENCY_CONTACT,
            from_=TWILIO_FROM_NUMBER,
            url="http://demo.twilio.com/docs/voice.xml"  # Can customize message
        )
        return f"Emergency call placed successfully. Call SID: {call.sid}"
    except Exception as e:
        return f"Twilio API Error: {str(e)}"



# Step3: Setup Location tool
