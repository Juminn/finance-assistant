from app.batch.sync import is_mass_deletion, plan_sync
from app.tools.catalog import ProductDoc


def doc(key: str, text: str, month: str = "202608") -> ProductDoc:
    return ProductDoc(
        product_key=key,
        category="정기예금",
        bank="가은행",
        name="가예금",
        text=text,
        disclosure_month=month,
    )


def test_처음_동기화하면_전부_색인_대상이다() -> None:
    docs = [doc("deposit:A:1", "내용 A"), doc("deposit:B:2", "내용 B")]
    plan = plan_sync(docs, existing={})

    assert [d.product_key for d in plan.to_index] == ["deposit:A:1", "deposit:B:2"]
    assert plan.to_delete == []
    assert plan.unchanged == 0


def test_내용이_그대로면_다시_임베딩하지_않는다() -> None:
    unchanged = doc("deposit:A:1", "내용 A")
    plan = plan_sync([unchanged], existing={unchanged.product_key: unchanged.content_hash})

    assert plan.to_index == []
    assert plan.unchanged == 1


def test_내용이_바뀐_상품만_다시_색인한다() -> None:
    old = doc("deposit:A:1", "예전 내용")
    new = doc("deposit:A:1", "새 내용")
    plan = plan_sync([new], existing={old.product_key: old.content_hash})

    assert [d.product_key for d in plan.to_index] == ["deposit:A:1"]
    assert plan.unchanged == 0


def test_사라진_상품은_삭제_대상이다() -> None:
    keep = doc("deposit:A:1", "내용 A")
    plan = plan_sync(
        [keep],
        existing={keep.product_key: keep.content_hash, "deposit:GONE:9": "hash"},
    )

    assert plan.to_delete == ["deposit:GONE:9"]
    assert plan.unchanged == 1


def test_공시월만_바뀌어도_다시_색인한다() -> None:
    old = doc("deposit:A:1", "같은 내용", month="202607")
    new = doc("deposit:A:1", "같은 내용", month="202608")
    assert old.content_hash != new.content_hash
    plan = plan_sync([new], existing={old.product_key: old.content_hash})
    assert [d.product_key for d in plan.to_index] == ["deposit:A:1"]


def test_수집이_통째로_비면_아무것도_삭제하지_않는다() -> None:
    plan = plan_sync([], existing={"deposit:A:1": "h1", "saving:B:2": "h2"})
    assert plan.to_delete == []
    assert plan.to_index == []


def test_수집되지_않은_카테고리의_키는_삭제하지_않는다() -> None:
    # deposit만 수집됨(saving 엔드포인트 일시 장애 가정) → saving 키는 보존
    collected = doc("deposit:A:1", "내용 A")
    plan = plan_sync(
        [collected],
        existing={
            collected.product_key: collected.content_hash,
            "deposit:GONE:9": "h",  # 같은 카테고리에서 사라짐 → 삭제
            "saving:B:2": "h",  # 수집 안 된 카테고리 → 보존
        },
    )
    assert plan.to_delete == ["deposit:GONE:9"]


def test_소수_삭제는_정상으로_본다() -> None:
    assert is_mass_deletion(5, existing_count=1000) is False


def test_색인_대부분을_지우려_하면_대량삭제로_막는다() -> None:
    # 한 권역 응답이 조용히 비어 오면 그 권역 상품이 통째로 삭제 대상이 된다.
    assert is_mass_deletion(300, existing_count=1000) is True


def test_삭제할_게_없으면_대량삭제가_아니다() -> None:
    assert is_mass_deletion(0, existing_count=0) is False
    assert is_mass_deletion(0, existing_count=1000) is False
