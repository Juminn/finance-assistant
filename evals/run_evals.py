"""의도분류 골든셋 평가.

실행: uv run python evals/run_evals.py
프롬프트나 그래프 구조를 바꾸면 반드시 로컬에서 실행해 정확도 회귀를 확인한다.
(실제 LLM을 호출하므로 CI에서는 돌리지 않는다.)
"""

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

THRESHOLD = 0.9
_GOLDEN_PATH = Path(__file__).parent / "golden.jsonl"


@dataclass
class EvalRecord:
    question: str
    intent: str


@dataclass
class WrongAnswer:
    question: str
    expected: str
    actual: str


@dataclass
class EvalReport:
    total: int
    correct: int
    wrong: list[WrongAnswer] = field(default_factory=list[WrongAnswer])

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


def load_golden(path: Path = _GOLDEN_PATH) -> list[EvalRecord]:
    records: list[EvalRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        records.append(EvalRecord(question=row["question"], intent=row["intent"]))
    return records


def evaluate(records: list[EvalRecord], classify: Callable[[EvalRecord], str]) -> EvalReport:
    report = EvalReport(total=len(records), correct=0)
    for record in records:
        actual = classify(record)
        if actual == record.intent:
            report.correct += 1
        else:
            report.wrong.append(
                WrongAnswer(question=record.question, expected=record.intent, actual=actual)
            )
    return report


def _classify_with_llm(record: EvalRecord) -> str:
    from langchain_core.messages import HumanMessage

    from app.agents.graph import supervisor

    update = supervisor({"messages": [HumanMessage(record.question)], "intent": "general"})
    return str(update["intent"])


def main() -> int:
    from app.core.config import get_settings

    if not get_settings().openai_api_key:
        print("OPENAI_API_KEY가 .env에 없어 eval을 실행할 수 없습니다.")
        return 1

    records = load_golden()
    print(f"골든셋 {len(records)}건 평가 중...")
    report = evaluate(records, classify=_classify_with_llm)

    print(f"\n의도분류 정확도: {report.accuracy:.1%} ({report.correct}/{report.total})")
    for wrong in report.wrong:
        print(f"  [오답] {wrong.question!r}: 예상 {wrong.expected} → 실제 {wrong.actual}")

    if report.accuracy < THRESHOLD:
        print(f"\n기준({THRESHOLD:.0%}) 미달 — 프롬프트 회귀를 확인하세요.")
        return 1
    print("\n기준 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
