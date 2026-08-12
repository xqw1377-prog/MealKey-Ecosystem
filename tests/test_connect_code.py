from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_mobile_connect_code_and_confirm_flow() -> None:
    seed = client.post("/dev/seed")
    assert seed.status_code == 200
    store_id = seed.json()["store_id"]

    created = client.post(f"/workspace/stores/{store_id}/connect-codes", params={"platform": "meituan"})
    assert created.status_code == 200
    body = created.json()
    code = body["code"]
    assert len(code) >= 4
    assert body["status"] == "pending"
    assert body["expires_in_seconds"] > 0

    status = client.get(f"/workspace/stores/{store_id}/connect-codes/{code}")
    assert status.status_code == 200
    assert status.json()["status"] == "pending"
    assert status.json()["platform"] == "meituan"

    links = client.get(f"/workspace/stores/{store_id}/platform-links")
    assert links.status_code == 200
    assert any(row.get("platform") == "meituan" and row.get("status") == "pending" for row in links.json()["links"])

    confirmed = client.post(f"/workspace/stores/{store_id}/platform-links/{code}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["link"]["status"] == "connected"

    status_after = client.get(f"/workspace/stores/{store_id}/connect-codes/{code}")
    assert status_after.status_code == 200
    assert status_after.json()["status"] == "connected"

    links_after = client.get(f"/workspace/stores/{store_id}/platform-links")
    assert any(
        row.get("platform") == "meituan" and row.get("status") == "connected"
        for row in links_after.json()["links"]
    )


def test_connect_code_not_found() -> None:
    seed = client.post("/dev/seed")
    assert seed.status_code == 200
    store_id = seed.json()["store_id"]

    missing = client.get(f"/workspace/stores/{store_id}/connect-codes/ZZZZZZ")
    assert missing.status_code == 404
