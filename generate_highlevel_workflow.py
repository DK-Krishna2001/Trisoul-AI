from diagrams import Cluster, Diagram, Edge

from diagrams.firebase.base import Firebase
from diagrams.gcp.database import Firestore
from diagrams.onprem.client import Client, User
from diagrams.onprem.compute import Server
from diagrams.onprem.network import Internet
from diagrams.programming.framework import Fastapi


with Diagram(
    "Trisoul Parallel Streaming Architecture",
    show=False,
    filename="trisoul_parallel_architecture",
    outformat="png",
    direction="TB",
):
    user = User("Patient / User")

    with Cluster("Client Interfaces"):
        ui = Client("Web UI\n(streaming chat)")
        speech = Client("Web Speech API")
        whatsapp = Client("WhatsApp (Twilio)")
        auth = Firebase("Firebase Auth")

    with Cluster("FastAPI Backend"):
        gateway = Fastapi("FastAPI /ask\n(JSON + stream)")
        save_user = Server("Save User Message")
        workers = Server("Background Evaluators")
        doc_parser = Server("Attachment Parser\n(PyMuPDF / image handoff)")

    with Cluster("Context Layer"):
        memory = Server("Memory Retrieval\nChromaDB + session history")
        firestore = Firestore("Firestore")

    with Cluster("LangGraph Decision Engine"):
        router = Server("Fast Router\n(llama-3.1-8b-instant)")

        with Cluster("Fast Utility Paths"):
            emergency = Server("Emergency Flow")
            locator = Internet("Therapist Locator\n(Google Maps)")
            twilio_api = Internet("Twilio Call API")

        with Cluster("Parallel Therapy Branch"):
            clinical = Server("Clinical Notes")
            sentiment = Server("Sentiment Analysis")

        synthesis = Server("Synthesis Model\n(gpt-oss-120b)")
        guard = Server("Response Guard\n(rewrite / polish)")

    # User and client layer
    user >> ui
    user >> speech
    user >> whatsapp
    ui >> auth

    # Input paths
    ui >> Edge(label="/ask?stream=true") >> gateway
    speech >> Edge(label="/transcribe") >> gateway
    whatsapp >> Edge(label="Webhook") >> gateway

    # Preparation and context
    gateway >> save_user >> firestore
    gateway >> doc_parser >> memory
    gateway >> memory
    firestore >> memory
    memory >> router

    # Decision branches
    router >> Edge(color="red", label="EMERGENCY") >> emergency >> twilio_api
    router >> Edge(color="darkorange", label="LOCATE_THERAPIST") >> locator
    router >> Edge(color="blue", label="THERAPY") >> clinical
    router >> Edge(color="blue", label="THERAPY") >> sentiment

    # Parallel converge
    clinical >> synthesis
    sentiment >> synthesis
    synthesis >> Edge(color="purple", label="token stream") >> gateway
    synthesis >> guard
    guard >> Edge(color="purple", label="final corrected text") >> gateway

    # Output and persistence
    emergency >> Edge(label="final response") >> gateway
    locator >> Edge(label="final response") >> gateway
    gateway >> Edge(style="dashed", label="save AI response") >> firestore
    gateway >> Edge(style="dashed", label="mood/title jobs") >> workers >> firestore

    # Return paths
    gateway >> Edge(color="purple", label="NDJSON chunks") >> ui
    gateway >> whatsapp
