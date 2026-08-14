from app.services.copy_humanize import humanize_operator_text, looks_like_jargon
from app.services.execution_pack import build_execution_pack, infer_pack_action_type, pack_from_card
from app.schemas.arbiter import DecisionAction, DecisionCard


def test_humanize_strips_baseline_and_ctr() -> None:
    text = humanize_operator_text("ctr 较baseline_window 下降 15.4%")
    assert "baseline_window" not in text
    assert "ctr" not in text.lower()
    assert "点击率" in text
    assert "基线期" in text
    assert not looks_like_jargon(text)


def test_image_title_review_packs_are_copyable() -> None:
    image = build_execution_pack("change_main_image", object_name="黑椒饭", title="先换主图")
    title = build_execution_pack("change_title", object_name="黑椒饭")
    review = build_execution_pack("batch_reply_negative_reviews")
    ordinary = build_execution_pack("reply_ordinary_reviews")
    appeal = build_execution_pack("appeal_pack")
    assert image and "复制" not in image["copy_text"]
    assert "真实" in image["copy_text"] or "实拍" in image["copy_text"]
    assert "CTR" not in image["copy_text"]
    assert "baseline_window" not in image["copy_text"]
    assert title and "20 字" in title["copy_text"]
    assert review and "先致歉" in review["copy_text"]
    assert ordinary and "差评" in ordinary["guardrail"]
    assert appeal and "工单号" in appeal["copy_text"]
    assert appeal["action_spec"]["type"] == "SUBMIT_REVIEW_APPEAL"
    for pack in (image, title, review, ordinary, appeal):
        assert pack["how_to_use"]
        assert pack["watch"]
        assert pack["steps"]
        assert pack["action_spec"]["version"] == "clv1"
        assert pack["action_spec"]["requires_approval"] is True
        assert pack["action_spec"]["execution_package"]["instructions"]


def test_action_spec_uses_registry_shape() -> None:
    pack = build_execution_pack("change_title", object_name="黑椒饭")
    spec = pack["action_spec"]
    assert spec["type"] == "CHANGE_PRODUCT_TITLE"
    assert spec["subject"]["type"] == "sku"
    assert spec["risk_level"] == "LOW"
    assert spec["success_metric"]["metric"] == "ctr"
    assert spec["observation_window_hours"] == 48


def test_pack_from_card_infers_main_image() -> None:
    card = DecisionCard(
        id="nba-1",
        title="把黑椒饭主图换成份量特写",
        arbiter_state="confirm",
        interrupt_reason="anomaly",
        queue_bucket="need_you",
        actions=[DecisionAction(label="按这个做", kind="adopt")],
    )
    assert infer_pack_action_type(title=card.title) == "change_main_image"
    pack = pack_from_card(card)
    assert pack is not None
    assert pack["action_type"] == "change_main_image"
    assert "黑椒饭" in pack["title"]
