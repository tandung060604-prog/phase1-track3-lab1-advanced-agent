from __future__ import annotations
import os
import re
from typing import Literal
from .llm_client import chat_completion, parse_json_object
from .prompts import ACTOR_SYSTEM, EVALUATOR_SYSTEM, REFLECTOR_SYSTEM
from .schemas import QAExample, JudgeResult, ReflectionEntry
from .utils import answers_match, normalize_answer

FIRST_ATTEMPT_WRONG = {"hp2": "London", "hp4": "Atlantic Ocean", "hp6": "Red Sea", "hp8": "Andes"}
FAILURE_MODE_BY_QID = {"hp2": "incomplete_multi_hop", "hp4": "wrong_final_answer", "hp6": "entity_drift", "hp8": "entity_drift"}
_ATTEMPT_TOKENS = 0
_ATTEMPT_LATENCY_MS = 0

def runtime_mode() -> Literal["mock", "llm"]:
    mode = os.getenv("REFLEXION_RUNTIME", "mock").strip().lower()
    return "llm" if mode in {"llm", "openai"} else "mock"

def reset_attempt_metrics() -> None:
    global _ATTEMPT_TOKENS, _ATTEMPT_LATENCY_MS
    _ATTEMPT_TOKENS = 0
    _ATTEMPT_LATENCY_MS = 0

def consume_attempt_metrics() -> tuple[int, int]:
    return _ATTEMPT_TOKENS, _ATTEMPT_LATENCY_MS

def _record_metrics(tokens: int, latency_ms: int) -> None:
    global _ATTEMPT_TOKENS, _ATTEMPT_LATENCY_MS
    _ATTEMPT_TOKENS += max(tokens, 0)
    _ATTEMPT_LATENCY_MS += max(latency_ms, 0)

def _context_text(example: QAExample) -> str:
    max_chunks = int(os.getenv("REFLEXION_CONTEXT_CHUNKS", "0") or "0")
    chunks = example.context
    if max_chunks > 0 and len(chunks) > max_chunks:
        question_terms = set(re.findall(r"[a-z0-9]+", example.question.lower()))
        ranked = sorted(
            chunks,
            key=lambda chunk: len(question_terms & set(re.findall(r"[a-z0-9]+", f"{chunk.title} {chunk.text}".lower()))),
            reverse=True,
        )
        chunks = ranked[:max_chunks]
    return "\n\n".join(f"[{chunk.title}]\n{chunk.text}" for chunk in chunks)

def _exact_evaluator(example: QAExample, answer: str) -> JudgeResult:
    if answers_match(example.gold_answer, answer):
        return JudgeResult(score=1, reason="Final answer matches the gold answer after normalization.")
    return JudgeResult(
        score=0,
        reason="Predicted answer does not match the gold answer after normalization.",
        missing_evidence=["Need to recover the exact gold answer from the context."],
        spurious_claims=[answer] if answer else [],
    )

def actor_answer(example: QAExample, attempt_id: int, agent_type: str, reflection_memory: list[str]) -> str:
    if runtime_mode() == "llm":
        reflections = "\n".join(f"- {item}" for item in reflection_memory) or "None"
        user_prompt = f"""Question:
{example.question}

Context:
{_context_text(example)}

Attempt: {attempt_id}
Agent type: {agent_type}
Reflection memory:
{reflections}

Return the final answer only."""
        response = chat_completion(ACTOR_SYSTEM, user_prompt, model_env="ACTOR_MODEL")
        _record_metrics(response.total_tokens, response.latency_ms)
        return response.text

    if example.qid not in FIRST_ATTEMPT_WRONG:
        return example.gold_answer
    if agent_type == "react":
        return FIRST_ATTEMPT_WRONG[example.qid]
    if attempt_id == 1 and not reflection_memory:
        return FIRST_ATTEMPT_WRONG[example.qid]
    return example.gold_answer

def evaluator(example: QAExample, answer: str) -> JudgeResult:
    if os.getenv("REFLEXION_EVALUATOR", "llm").strip().lower() == "exact":
        return _exact_evaluator(example, answer)

    if runtime_mode() == "llm":
        user_prompt = f"""Question:
{example.question}

Gold answer:
{example.gold_answer}

Predicted answer:
{answer}

Context:
{_context_text(example)}

Return JSON only."""
        response = chat_completion(EVALUATOR_SYSTEM, user_prompt, response_format="json", model_env="EVALUATOR_MODEL")
        _record_metrics(response.total_tokens, response.latency_ms)
        payload = parse_json_object(response.text)
        return JudgeResult.model_validate(payload)

    if normalize_answer(example.gold_answer) == normalize_answer(answer):
        return JudgeResult(score=1, reason="Final answer matches the gold answer after normalization.")
    if normalize_answer(answer) == "london":
        return JudgeResult(score=0, reason="The answer stopped at the birthplace city and never completed the second hop to the river.", missing_evidence=["Need to identify the river that flows through London."], spurious_claims=[])
    return JudgeResult(score=0, reason="The final answer selected the wrong second-hop entity.", missing_evidence=["Need to ground the answer in the second paragraph."], spurious_claims=[answer])

def reflector(example: QAExample, attempt_id: int, judge: JudgeResult, wrong_answer: str = "") -> ReflectionEntry:
    if runtime_mode() == "llm":
        user_prompt = f"""Question:
{example.question}

Previous wrong answer:
{wrong_answer}

Evaluator reason:
{judge.reason}

Missing evidence:
{judge.missing_evidence}

Spurious claims:
{judge.spurious_claims}

Context:
{_context_text(example)}

Attempt id: {attempt_id}
Return JSON only."""
        response = chat_completion(REFLECTOR_SYSTEM, user_prompt, response_format="json", model_env="REFLECTOR_MODEL")
        _record_metrics(response.total_tokens, response.latency_ms)
        payload = parse_json_object(response.text)
        payload["attempt_id"] = int(payload.get("attempt_id") or attempt_id)
        return ReflectionEntry.model_validate(payload)

    strategy = "Do the second hop explicitly: birthplace city -> river through that city." if example.qid == "hp2" else "Verify the final entity against the second paragraph before answering."
    return ReflectionEntry(attempt_id=attempt_id, failure_reason=judge.reason, lesson="A partial first-hop answer is not enough; the final answer must complete all hops.", next_strategy=strategy)
