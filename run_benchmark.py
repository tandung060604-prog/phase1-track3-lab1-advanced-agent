from __future__ import annotations
import json
import os
from pathlib import Path
import typer
from rich import print
from typing_extensions import Annotated
from src.reflexion_lab.agents import ReActAgent, ReflexionAgent
from src.reflexion_lab.reporting import build_report, save_report
from src.reflexion_lab.utils import load_dataset, save_jsonl
app = typer.Typer(add_completion=False)

@app.command()
def main(
    dataset: str = "data/hotpot_mini.json",
    out_dir: str = "outputs/sample_run",
    reflexion_attempts: int = 3,
    mode: Annotated[str, typer.Option(help="Runtime mode: mock or llm")] = "mock",
    limit: Annotated[int, typer.Option(help="Run only the first N examples; 0 means all")] = 0,
    evaluator_mode: Annotated[str, typer.Option(help="Evaluator mode: llm or exact")] = "llm",
    context_chunks: Annotated[int, typer.Option(help="Top-ranked context chunks to keep; 0 means all")] = 0,
    agents: Annotated[str, typer.Option(help="Agents to run: react, reflexion, or both")] = "both",
) -> None:
    if mode not in {"mock", "llm"}:
        raise typer.BadParameter("mode must be either 'mock' or 'llm'")
    if evaluator_mode not in {"llm", "exact"}:
        raise typer.BadParameter("evaluator-mode must be either 'llm' or 'exact'")
    if agents not in {"react", "reflexion", "both"}:
        raise typer.BadParameter("agents must be one of: react, reflexion, both")
    os.environ["REFLEXION_RUNTIME"] = mode
    os.environ["REFLEXION_EVALUATOR"] = evaluator_mode
    os.environ["REFLEXION_CONTEXT_CHUNKS"] = str(context_chunks)
    examples = load_dataset(dataset)
    if limit > 0:
        examples = examples[:limit]
    react = ReActAgent()
    reflexion = ReflexionAgent(max_attempts=reflexion_attempts)
    try:
        react_records = [react.run(example) for example in examples] if agents in {"react", "both"} else []
        reflexion_records = [reflexion.run(example) for example in examples] if agents in {"reflexion", "both"} else []
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc
    all_records = react_records + reflexion_records
    out_path = Path(out_dir)
    save_jsonl(out_path / "react_runs.jsonl", react_records)
    save_jsonl(out_path / "reflexion_runs.jsonl", reflexion_records)
    report = build_report(all_records, dataset_name=Path(dataset).name, mode=mode)
    json_path, md_path = save_report(report, out_path)
    print(f"[green]Saved[/green] {json_path}")
    print(f"[green]Saved[/green] {md_path}")
    print(json.dumps(report.summary, indent=2))

if __name__ == "__main__":
    app()
