from __future__ import annotations
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from .schemas import ReportPayload, RunRecord

def summarize(records: list[RunRecord]) -> dict:
    grouped: dict[str, list[RunRecord]] = defaultdict(list)
    for record in records:
        grouped[record.agent_type].append(record)
    summary: dict[str, dict] = {}
    for agent_type, rows in grouped.items():
        summary[agent_type] = {"count": len(rows), "em": round(mean(1.0 if r.is_correct else 0.0 for r in rows), 4), "avg_attempts": round(mean(r.attempts for r in rows), 4), "avg_token_estimate": round(mean(r.token_estimate for r in rows), 2), "avg_latency_ms": round(mean(r.latency_ms for r in rows), 2)}
    if "react" in summary and "reflexion" in summary:
        summary["delta_reflexion_minus_react"] = {"em_abs": round(summary["reflexion"]["em"] - summary["react"]["em"], 4), "attempts_abs": round(summary["reflexion"]["avg_attempts"] - summary["react"]["avg_attempts"], 4), "tokens_abs": round(summary["reflexion"]["avg_token_estimate"] - summary["react"]["avg_token_estimate"], 2), "latency_abs": round(summary["reflexion"]["avg_latency_ms"] - summary["react"]["avg_latency_ms"], 2)}
    return summary

def failure_breakdown(records: list[RunRecord]) -> dict:
    grouped: dict[str, Counter] = defaultdict(Counter)
    for record in records:
        grouped[record.agent_type][record.failure_mode] += 1
        grouped["overall"][record.failure_mode] += 1
    return {agent: dict(counter) for agent, counter in grouped.items()}

def build_report(records: list[RunRecord], dataset_name: str, mode: str = "mock") -> ReportPayload:
    examples = [{"qid": r.qid, "agent_type": r.agent_type, "gold_answer": r.gold_answer, "predicted_answer": r.predicted_answer, "is_correct": r.is_correct, "attempts": r.attempts, "failure_mode": r.failure_mode, "reflection_count": len(r.reflections)} for r in records]
    discussion = (
        "Reflexion giúp cải thiện câu trả lời khi lần thử đầu tiên dừng lại sau bước đầu tiên (hop đầu) hoặc bị lệch sang một thực thể sai ở bước thứ hai (entity drift). "
        "Thử nghiệm này so sánh mô hình cơ sở ReAct chạy một lần với tác nhân Reflexion chạy nhiều lần, từ đó báo cáo phản ánh "
        "sự đánh đổi giữa độ chính xác và chi phí tài nguyên. Các dạng lỗi (failure modes) chính cần xem xét bao gồm: suy luận đa bước chưa hoàn thiện (incomplete multi-hop reasoning), "
        "lệch thực thể khi đi theo đoạn văn bổ trợ sai (entity drift), và câu trả lời cuối cùng bị sai mặc dù có vẻ hợp lý nhưng không được chứng thực bởi ngữ cảnh. "
        "Reflexion có thể khắc phục một số lỗi này bằng cách chuyển đổi phản hồi từ bộ đánh giá (evaluator) thành chiến thuật hành động cụ thể tiếp theo, tuy nhiên nó cũng làm tăng số lần thử, lượng token tiêu thụ và độ trễ (latency)."
    )
    extensions = [
        "structured_evaluator",
        "reflection_memory",
        "benchmark_report_json",
        "mock_mode_for_autograding",
    ]
    return ReportPayload(meta={"dataset": dataset_name, "mode": mode, "num_records": len(records), "agents": sorted({r.agent_type for r in records})}, summary=summarize(records), failure_modes=failure_breakdown(records), examples=examples, extensions=extensions, discussion=discussion)

def save_report(report: ReportPayload, out_dir: str | Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"
    json_path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
    s = report.summary
    react = s.get("react", {})
    reflexion = s.get("reflexion", {})
    delta = s.get("delta_reflexion_minus_react", {})
    ext_lines = "\n".join(f"- {item}" for item in report.extensions) or "Không có"
    md = f"""# Báo cáo Đánh giá Hiệu năng Lab 16

## Thông tin chung (Metadata)
- Bộ dữ liệu (Dataset): {report.meta['dataset']}
- Chế độ chạy (Mode): {report.meta['mode']}
- Số lượng bản ghi (Records): {report.meta['num_records']}
- Các Agent: {', '.join(report.meta['agents'])}

## Kết quả tóm tắt (Summary)
| Chỉ số (Metric) | ReAct | Reflexion | Chênh lệch (Delta) |
|---|---:|---:|---:|
| Tỉ lệ khớp chính xác (EM) | {react.get('em', 0)} | {reflexion.get('em', 0)} | {delta.get('em_abs', 0)} |
| Số lần thử trung bình (Avg attempts) | {react.get('avg_attempts', 0)} | {reflexion.get('avg_attempts', 0)} | {delta.get('attempts_abs', 0)} |
| Ước tính token trung bình (Avg token estimate) | {react.get('avg_token_estimate', 0)} | {reflexion.get('avg_token_estimate', 0)} | {delta.get('tokens_abs', 0)} |
| Độ trễ trung bình (Avg latency - ms) | {react.get('avg_latency_ms', 0)} | {reflexion.get('avg_latency_ms', 0)} | {delta.get('latency_abs', 0)} |

## Phân tích các dạng lỗi (Failure modes)
```json
{json.dumps(report.failure_modes, indent=2)}
```

## Các phần mở rộng đã triển khai (Extensions implemented)
{ext_lines}

## Thảo luận (Discussion)
{report.discussion}
"""
    md_path.write_text(md, encoding="utf-8")
    return json_path, md_path
