"""访谈 HTTP 契约：key 传递、MOS 刷新、NL miss 422、轻量端点。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _seed_store() -> str:
    seed = client.post("/dev/seed")
    assert seed.status_code == 200
    return seed.json()["store_id"]


def test_interview_get_next_question_is_fast_and_typed() -> None:
    store_id = _seed_store()
    first = client.post(f"/stores/{store_id}/understanding/interview")
    assert first.status_code == 200
    body = first.json()
    assert body["gap_key"]
    assert body["gap_key"] != "mue_gap"
    assert isinstance(body["question"], str)
    assert body["question"]
    assert "understanding" in body
    assert body["understanding"]["mos_satisfied"] is False


def test_interview_posts_key_and_refreshes_mos() -> None:
    store_id = _seed_store()
    answered = client.post(
        f"/stores/{store_id}/understanding/interview",
        json={"key": "priority_style", "answer": "提高排名"},
    )
    assert answered.status_code == 200
    body = answered.json()
    assert body.get("accepted") is True
    understanding = body["understanding"]
    assert understanding["preferences"]["priority_style"] == "rank"
    assert "priority_style" not in understanding["open_gaps"]
    assert "priority_style" not in understanding["mos_blocking_fields"]
    assert understanding["mos_satisfied"] is False
    if body.get("gap_key"):
        assert body["gap_key"] != "priority_style"
        assert body["gap_key"] != "mue_nl_setting"


def test_interview_nl_miss_keeps_current_question() -> None:
    store_id = _seed_store()
    current = client.post(f"/stores/{store_id}/understanding/interview")
    assert current.status_code == 200
    gap_key = current.json()["gap_key"]
    missed = client.post(
        f"/stores/{store_id}/understanding/interview",
        json={"key": gap_key, "answer": "今天天气真好啊完全无关"},
    )
    assert missed.status_code == 422
    body = missed.json()
    assert body.get("accepted") is False
    assert body.get("gap_key") == gap_key
    assert isinstance(body.get("question"), str)


def test_understanding_get_does_not_require_full_agents() -> None:
    store_id = _seed_store()
    got = client.get(f"/stores/{store_id}/understanding")
    assert got.status_code == 200
    payload = got.json()
    assert payload["store_id"] == store_id
    assert "mos_blocking_fields" in payload
    assert "mos_gap_keys" in payload
    assert "platform_connected" in payload
