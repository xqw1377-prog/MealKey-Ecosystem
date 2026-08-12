from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_settings_overview_and_store_update() -> None:
    seed = client.post("/dev/seed")
    assert seed.status_code == 200
    store_id = seed.json()["store_id"]

    overview = client.get("/settings/overview", params={"store_id": store_id})
    assert overview.status_code == 200
    body = overview.json()
    assert "checklist" in body
    assert body["store"]["store_id"] == store_id

    updated = client.put(
        f"/settings/stores/{store_id}",
        json={"name": "测试门店", "city": "上海", "area": "静安", "category": "快餐", "audience": "写字楼"},
    )
    assert updated.status_code == 200
    assert updated.json()["store"]["name"] == "测试门店"
    assert updated.json()["checklist"]["completed"] >= 2


def test_demo_platform_connect_and_assist() -> None:
    seed = client.post("/dev/seed")
    store_id = seed.json()["store_id"]

    connected = client.post(
        f"/settings/stores/{store_id}/platforms/connect",
        json={"platform": "meituan", "mode": "mock", "run_daily_job": True},
    )
    assert connected.status_code == 200
    assert connected.json()["sync"]["menu_upserted"] >= 1

    links = client.get(f"/settings/stores/{store_id}/platforms")
    assert links.status_code == 200
    assert any(row["status"] == "connected" for row in links.json()["links"])

    assist = client.post("/settings/assist/ask", json={"question": "怎么对接美团？", "store_id": store_id})
    assert assist.status_code == 200
    assert assist.json()["intent"] == "platform"

    deploy = client.get("/settings/assist/deploy")
    assert deploy.status_code == 200
    assert deploy.json()["steps"]


def test_system_setting_mask_not_overwritten() -> None:
    put = client.put(
        "/settings/system",
        json={"settings": [{"key": "platform_connector_url", "value": "http://127.0.0.1:9000/sync"}]},
    )
    assert put.status_code == 200
    assert any(
        row["key"] == "platform_connector_url" and row["configured"] for row in put.json()["settings"]
    )

    masked = client.put(
        "/settings/system",
        json={"settings": [{"key": "platform_connector_token", "value": "tok***en"}]},
    )
    assert masked.status_code == 200
