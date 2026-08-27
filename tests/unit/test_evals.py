from evals.run_evals import EvalRecord, evaluate, load_golden


def test_골든셋_파일을_로드한다() -> None:
    records = load_golden()
    assert len(records) >= 80
    assert all(r.intent in ("deposit", "loan", "general") for r in records)
    assert all(r.tier in ("core", "boundary") for r in records)


def test_골든셋에_중복_문항이_없다() -> None:
    questions = [r.question for r in load_golden()]
    assert len(set(questions)) == len(questions)


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


def test_tier별로_정확도를_따로_낸다() -> None:
    # boundary는 원래 낮게 나오므로 core와 섞어서 보면 회귀를 못 잡는다
    records = [
        EvalRecord(question="예금 비교", intent="deposit", tier="core"),
        EvalRecord(question="돈 모으고 싶어", intent="deposit", tier="boundary"),
    ]
    report = evaluate(records, classify=lambda r: "deposit" if r.tier == "core" else "general")
    assert report.subset(tier="core").accuracy == 1.0
    assert report.subset(tier="boundary").accuracy == 0.0
    assert report.accuracy == 0.5


def test_라벨별로_정확도를_따로_낸다() -> None:
    records = [
        EvalRecord(question="예금 비교", intent="deposit"),
        EvalRecord(question="대출 비교", intent="loan"),
    ]
    report = evaluate(records, classify=lambda r: "deposit")
    assert report.subset(intent="deposit").accuracy == 1.0
    assert report.subset(intent="loan").accuracy == 0.0


def test_비어있는_부분집합의_정확도는_0이다() -> None:
    report = evaluate([EvalRecord("안녕", "general")], classify=lambda r: r.intent)
    assert report.subset(tier="boundary").total == 0
    assert report.subset(tier="boundary").accuracy == 0.0
