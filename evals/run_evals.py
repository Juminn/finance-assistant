"""의도분류 골든셋 평가.

실행: uv run python evals/run_evals.py
프롬프트나 그래프 구조를 바꾸면 반드시 로컬에서 실행해 정확도 회귀를 확인한다.
(실제 LLM을 호출하므로 CI에서는 돌리지 않는다.)

기본으로는 LangSmith에 트레이싱하지 않는다 (89문항 = 89트레이스라 무료 한도를 잡아먹는다).
오답 원인을 추적할 때만 --trace를 붙이면 이 실행의 LLM 호출이 트레이싱된다.

라벨링 규칙과 tier의 의미는 evals/README.md 참고.
기준선은 core tier에만 건다 — boundary는 원래 낮게 나오는 문항 묶음이라
함께 평균 내면 회귀가 묻힌다.
"""

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

CORE_THRESHOLD = 0.9
_GOLDEN_PATH = Path(__file__).parent / "golden.jsonl"
_INTENTS = ("deposit", "loan", "general")


@dataclass
class EvalRecord:
    question: str
    intent: str
    tier: str = "core"


@dataclass
class WrongAnswer:
    question: str
    expected: str
    actual: str
    tier: str = "core"


@dataclass
class Outcome:
    record: EvalRecord
    actual: str

    @property
    def is_correct(self) -> bool:
        return self.actual == self.record.intent


@dataclass
class EvalReport:
    outcomes: list[Outcome] = field(default_factory=list[Outcome])

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def correct(self) -> int:
        return sum(1 for o in self.outcomes if o.is_correct)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def wrong(self) -> list[WrongAnswer]:
        return [
            WrongAnswer(
                question=o.record.question,
                expected=o.record.intent,
                actual=o.actual,
                tier=o.record.tier,
            )
            for o in self.outcomes
            if not o.is_correct
        ]

    def subset(self, *, tier: str | None = None, intent: str | None = None) -> "EvalReport":
        """tier·정답라벨로 잘라낸 부분 리포트."""
        return EvalReport(
            [
                o
                for o in self.outcomes
                if (tier is None or o.record.tier == tier)
                and (intent is None or o.record.intent == intent)
            ]
        )


def load_golden(path: Path = _GOLDEN_PATH) -> list[EvalRecord]:
    records: list[EvalRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        records.append(
            EvalRecord(
                question=row["question"],
                intent=row["intent"],
                tier=row.get("tier", "core"),
            )
        )
    return records


def evaluate(records: list[EvalRecord], classify: Callable[[EvalRecord], str]) -> EvalReport:
    return EvalReport([Outcome(record=r, actual=classify(r)) for r in records])


def _classify_with_llm(record: EvalRecord) -> str:
    from langchain_core.messages import HumanMessage

    from app.agents.graph import supervisor

    update = supervisor({"messages": [HumanMessage(record.question)], "intent": "general"})
    return str(update["intent"])


def _print_breakdown(report: EvalReport) -> None:
    print(f"\n전체 정확도: {report.accuracy:.1%} ({report.correct}/{report.total})")

    print("\n  tier별")
    for tier in ("core", "boundary"):
        part = report.subset(tier=tier)
        if part.total:
            print(f"    {tier:9s} {part.accuracy:6.1%} ({part.correct}/{part.total})")

    print("\n  정답 라벨별 (core)")
    for intent in _INTENTS:
        part = report.subset(tier="core", intent=intent)
        if part.total:
            print(f"    {intent:9s} {part.accuracy:6.1%} ({part.correct}/{part.total})")


def main() -> int:
    from app.core.config import get_settings

    if "--trace" in sys.argv[1:]:
        import os

        from dotenv import load_dotenv

        # 이 실행만 트레이싱한다 — .env의 LANGSMITH_TRACING 값과 무관하게 켜고,
        # API 키 등 나머지 LANGSMITH_*는 .env에서 프로세스 환경으로 올린다
        os.environ["LANGSMITH_TRACING"] = "true"
        load_dotenv()

    if not get_settings().openai_api_key:
        print("OPENAI_API_KEY가 .env에 없어 eval을 실행할 수 없습니다.")
        return 1

    records = load_golden()
    print(f"골든셋 {len(records)}건 평가 중...")
    report = evaluate(records, classify=_classify_with_llm)
    _print_breakdown(report)

    if report.wrong:
        print("\n오답")
        for w in sorted(report.wrong, key=lambda x: x.tier):
            print(f"  [{w.tier}] {w.question!r}: 예상 {w.expected} → 실제 {w.actual}")

    core = report.subset(tier="core")
    if core.accuracy < CORE_THRESHOLD:
        print(f"\ncore 기준({CORE_THRESHOLD:.0%}) 미달 — 프롬프트 회귀를 확인하세요.")
        return 1
    print(f"\ncore 기준({CORE_THRESHOLD:.0%}) 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
