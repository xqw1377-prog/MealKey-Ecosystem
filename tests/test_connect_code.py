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
    connected_row = next(
        row for row in links_after.json()["links"] if row.get("platform") == "meituan"
    )
    assert connected_row.get("connector_mode") == "mobile"
    assert connected_row.get("connected_at")
    assert connected_row.get("connected_at") != connected_row.get("last_sync_at") or connected_row.get(
        "last_sync_at"
    )


def test_connect_code_survives_in_database() -> None:
    seed = client.post("/dev/seed")
    assert seed.status_code == 200
    store_id = seed.json()["store_id"]
    created = client.post(f"/workspace/stores/{store_id}/connect-codes", params={"platform": "eleme"})
    code = created.json()["code"]
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.settings import ConnectCode

    with SessionLocal() as db:
        row = db.execute(select(ConnectCode).where(ConnectCode.code == code)).scalar_one()
        assert row.store_id == store_id
        assert row.status == "pending"


def test_connect_code_not_found() -> None:
    seed = client.post("/dev/seed")
    assert seed.status_code == 200
    store_id = seed.json()["store_id"]

    missing = client.get(f"/workspace/stores/{store_id}/connect-codes/ZZZZZZ")
    assert missing.status_code == 404
