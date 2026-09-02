import os

from pydantic import ValidationError

# Importing the graph constructs SDK clients, but these tests never invoke them.
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
# googlemaps validates the API-key format on client construction; this is inert.
os.environ.setdefault("GOOGLE_MAPS_API_KEY", "AIza" + "x" * 35)

import ai_agent


class StubRouter:
    def __init__(self, intent):
        self.intent = intent
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return ai_agent.IntentDecision(intent_type=self.intent)


def test_fast_model_uses_supported_gpt_oss_with_low_reasoning():
    assert ai_agent.FAST_MODEL == "openai/gpt-oss-20b"
    assert ai_agent.llm_fast.model_name == ai_agent.FAST_MODEL
    assert ai_agent.FAST_REASONING_EFFORT == "low"
    assert ai_agent.llm_fast.reasoning_effort == "low"
    assert ai_agent.ROUTER_OUTPUT_METHOD == "json_schema"


def test_router_returns_schema_validated_intent(monkeypatch):
    stub = StubRouter("LOCATE_THERAPIST")
    monkeypatch.setattr(ai_agent, "llm_router", stub)

    result = ai_agent.router_node({"user_message": "Find a therapist near Buffalo, NY"})

    assert result == {"intent": "LOCATE_THERAPIST"}
    assert len(stub.messages) == 2


def test_intent_schema_rejects_unknown_values():
    try:
        ai_agent.IntentDecision(intent_type="OTHER")
    except ValidationError:
        pass
    else:
        raise AssertionError("Intent schema accepted an unsupported routing value")


def test_route_initial_selects_every_available_branch():
    assert ai_agent.route_initial({"intent": "EMERGENCY"}) == "emergency_tool"
    assert ai_agent.route_initial({"intent": "LOCATE_THERAPIST"}) == "locate_therapist_tool"
    assert ai_agent.route_initial({"intent": "THERAPY"}) == ["clinical", "sentiment"]


def test_emergency_node_invokes_its_tool_without_real_call(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_agent, "call_emergency", lambda: calls.append("called"))

    result = ai_agent.emergency_tool_node({})

    assert calls == ["called"]
    assert result["tool_called"] == "emergency_call_tool"
