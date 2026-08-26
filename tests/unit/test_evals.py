from evals.run_evals import EvalRecord, evaluate, load_golden


def test_골든셋_파일을_로드한다() -> None:
    records = load_golden()
    assert len(records) >= 20
    assert all(r.intent in ("deposit", "loan", "general") for r in records)


def test_전부_맞으면_정확도_1이고_오답_목록이_비어있다() -> None:
    records = [
        EvalRecord(question="예금 비교", intent="deposit"),
        EvalRecord(question="안녕", intent="general"),
    ]
    report = evaluate(records, classify=lambda r: r.intent)
    assert report.accuracy == 1.0
    assert report.wrong == []


def test_오답은_질문과_예상_실제_의도를_기록한다() -> None:
    records = [
        EvalRecord(question="예금 비교", intent="deposit"),
        EvalRecord(question="대출 비교", intent="loan"),
    ]
    report = evaluate(records, classify=lambda r: "general")
    assert report.accuracy == 0.0
    assert len(report.wrong) == 2
    assert report.wrong[0].expected == "deposit"
    assert report.wrong[0].actual == "general"
