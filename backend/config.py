import os
from dotenv import load_dotenv

load_dotenv()

TWILLIO_ACCOUNT_KK = os.getenv("TWILLIO_ACCOUNT_KK")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")
EMERGENCY_CONTACT = os.getenv("EMERGENCY_CONTACT")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TESTBENCH_PASSWORD = os.getenv("TESTBENCH_PASSWORD", "trisoul-bench")
