from app.batch.sync import plan_sync
from app.tools.catalog import ProductDoc


def doc(key: str, text: str) -> ProductDoc:
    return ProductDoc(
        product_key=key,
        category="정기예금",
        bank="가은행",
        name="가예금",
        text=text,
        disclosure_month="202608",
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
