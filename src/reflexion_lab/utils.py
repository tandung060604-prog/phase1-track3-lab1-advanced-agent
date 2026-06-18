from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Iterable
from .schemas import QAExample, RunRecord

def normalize_answer(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def answers_match(gold: str, predicted: str) -> bool:
    gold_norm = normalize_answer(gold)
    predicted_norm = normalize_answer(predicted)
    if not gold_norm or not predicted_norm:
        return gold_norm == predicted_norm
    if gold_norm == predicted_norm:
        return True
    if _negative_award_match(gold_norm, predicted_norm):
        return True
    return gold_norm in predicted_norm or predicted_norm in gold_norm

def _negative_award_match(gold_norm: str, predicted_norm: str) -> bool:
    no_award_gold = (
        gold_norm.startswith("no ")
        and "award" in gold_norm
        and any(term in gold_norm for term in {"win", "won"})
    )
    if not no_award_gold:
        return False
    negative_cues = (
        "did not win",
        "did not receive",
        "has not won",
        "no win",
        "no wins",
        "not win",
    )
    return "award" in predicted_norm and any(cue in predicted_norm for cue in negative_cues)

def load_dataset(path: str | Path) -> list[QAExample]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [QAExample.model_validate(item) for item in raw]

def save_jsonl(path: str | Path, records: Iterable[RunRecord]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(record.model_dump_json() + "\n")
