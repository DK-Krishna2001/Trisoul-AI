from __future__ import annotations

from dataclasses import dataclass, field
import re


@dataclass
class GuardrailDecision:
    route: str = "allow"
    safe_response: str = ""
    tool_called: str = "None"
    trigger_emergency_call: bool = False
    labels: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)


IMMINENT_TERMS = [
    "right now",
    "tonight",
    "today",
    "soon",
    "immediately",
    "after this",
    "this evening",
    "i'm going to",
    "i am going to",
    "i plan to",
]

SELF_HARM_PATTERNS = [
    "kill myself",
    "end my life",
    "want to die",
    "don't want to live",
    "do not want to live",
    "suicide",
    "hurt myself",
    "harm myself",
    "overdose",
    "cut myself",
]

VIOLENCE_PATTERNS = [
    "kill them",
    "hurt them",
    "stab them",
    "shoot them",
    "attack them",
]

DIAGNOSIS_REGEX = re.compile(
    r"\b(you have|you may have|this sounds like|it sounds like|you are experiencing)\s+"
    r"(bipolar|schizophrenia|ptsd|ocd|adhd|major depression|depression|anxiety disorder|borderline personality disorder)\b",
    re.IGNORECASE,
)

MEDICATION_REGEX = re.compile(
    r"\b(start taking|take|use|try)\s+(xanax|prozac|zoloft|lexapro|adderall|ssri|benzodiazepine|antidepressant)\b",
    re.IGNORECASE,
)

SECRECY_PATTERNS = [
    "don't tell anyone",
    "do not tell anyone",
    "keep this secret",
    "no need to call 911",
    "no need to call emergency services",
    "you do not need professional help",
]

SELF_HARM_INSTRUCTION_PATTERNS = [
    "you should hurt yourself",
    "you should kill yourself",
    "here's how to kill yourself",
    "here is how to kill yourself",
    "ways to die",
]


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def _contains_any(text: str, patterns: list[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def build_crisis_response(include_emergency_services: bool) -> str:
    if include_emergency_services:
        return (
            "I'm really glad you said this out loud. If you might act on these thoughts soon, "
            "please call 988 right now or call emergency services immediately. If you can, move "
            "away from anything you could use to hurt yourself and get to another person nearby. "
            "If you want, send one short message to someone you trust right now: 'I need you with me now.'"
        )

    return (
        "I'm really sorry you're carrying this much pain. You deserve immediate support, and I "
        "want to treat this seriously. Please contact 988 now if you're in the U.S. or reach out "
        "to a local crisis line or trusted person who can stay with you. If you feel like you may "
        "act on these thoughts, call emergency services right now."
    )


def evaluate_input_guardrails(user_message: str) -> GuardrailDecision:
    text = _normalize(user_message)
    labels: list[str] = []

    if _contains_any(text, SELF_HARM_PATTERNS):
        labels.append("self_harm")
        imminent = _contains_any(text, IMMINENT_TERMS)
        return GuardrailDecision(
            route="crisis_support",
            safe_response=build_crisis_response(include_emergency_services=imminent),
            tool_called="guardrail_crisis_support",
            trigger_emergency_call=imminent,
            labels=labels + (["imminent"] if imminent else []),
        )

    if _contains_any(text, VIOLENCE_PATTERNS):
        labels.append("violence_risk")
        imminent = _contains_any(text, IMMINENT_TERMS)
        return GuardrailDecision(
            route="crisis_support",
            safe_response=build_crisis_response(include_emergency_services=imminent),
            tool_called="guardrail_crisis_support",
            trigger_emergency_call=False,
            labels=labels + (["imminent"] if imminent else []),
        )

    return GuardrailDecision(labels=labels)


def detect_output_violations(response_text: str) -> list[str]:
    text = _normalize(response_text)
    violations: list[str] = []

    if DIAGNOSIS_REGEX.search(response_text or ""):
        violations.append("diagnosis")
    if MEDICATION_REGEX.search(response_text or ""):
        violations.append("medication_advice")
    if _contains_any(text, SECRECY_PATTERNS):
        violations.append("discourages_support")
    if _contains_any(text, SELF_HARM_INSTRUCTION_PATTERNS):
        violations.append("self_harm_instructions")

    return violations


def build_policy_boundary_response(user_message: str, violations: list[str]) -> str:
    text = _normalize(user_message)
    if _contains_any(text, SELF_HARM_PATTERNS) or _contains_any(text, VIOLENCE_PATTERNS):
        return build_crisis_response(include_emergency_services=True)

    if "medication_advice" in violations:
        return (
            "I want to be careful here. I can't tell you to start, stop, or change medication. "
            "If you're thinking about treatment, the safest next step is to speak with a licensed "
            "doctor or psychiatrist. I can still help you prepare questions for that conversation "
            "or talk through what symptoms you're dealing with."
        )

    if "diagnosis" in violations:
        return (
            "I want to be careful not to label or diagnose you from a chat. What you're feeling is "
            "real, and it would be better to talk about your symptoms, how long this has been going "
            "on, and what support would help right now. If you want, I can help you think through "
            "what to tell a licensed professional."
        )

    return (
        "I want to be careful and keep this supportive. I can't help with harmful instructions or "
        "unsafe advice. I can help you slow this down, focus on immediate safety, and figure out "
        "the next safe step."
    )


def apply_output_guardrails(user_message: str, response_text: str) -> GuardrailDecision:
    violations = detect_output_violations(response_text)
    if not violations:
        return GuardrailDecision(
            route="allow",
            safe_response=response_text,
            tool_called="None",
            violations=[],
        )

    return GuardrailDecision(
        route="rewrite",
        safe_response=build_policy_boundary_response(user_message, violations),
        tool_called="guardrail_output_block",
        violations=violations,
    )
