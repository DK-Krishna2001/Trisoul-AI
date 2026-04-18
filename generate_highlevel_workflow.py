from diagrams import Diagram, Cluster, Edge

from diagrams.onprem.client import User, Client
from diagrams.onprem.compute import Server
from diagrams.gcp.database import Firestore
from diagrams.onprem.network import Internet
from diagrams.firebase.base import Firebase
from diagrams.programming.framework import Fastapi

with Diagram("Trisoul Comprehensive End-to-End Workflow", show=False, filename="trisoul_comprehensive_architecture", outformat="png", direction="TB"):
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

    with Cluster("Intelligence Engine"):
        mem = Server("Memory & RAG Context")
        agent = Server("LangGraph ReAct Agent")
        
        with Cluster("Models"):
            groq = Server("Groq (Primary LLM)")
            openai = Server("OpenAI (Whisper/Vision)")
            medgemma = Server("MedGemma (Clinical)")
            
        with Cluster("Tools"):
            maps = Internet("Google Maps API")

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
    
    # Orchestration
    mem >> agent
    
    # LLMs & Tools
    agent >> Edge(color="green", label="Reasoning") >> groq
    agent >> Edge(color="blue", label="Audio/Vision") >> openai
    agent >> Edge(color="purple", label="Specialized") >> medgemma
    agent >> Edge(color="orange", label="Search") >> maps
    
    # Persistence & Background Tasks
    agent >> Edge(label="AI Response") >> gateway
    gateway >> Edge(style="dashed", label="Async Mood Scoring") >> workers
    workers >> db
    gateway >> Edge(label="Save Chats") >> db
    mem >> db
    
    # Returning to user
    gateway >> ui
    gateway >> whatsapp
