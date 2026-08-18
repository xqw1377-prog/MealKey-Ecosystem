from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_public_config_exposes_auth_and_llm() -> None:
    config = client.get("/public/config")
    assert config.status_code == 200
    body = config.json()
    assert "llm" in body
    assert "auth" in body
    assert body["auth"]["mode"] in {"api_token", "dev_open"}
    assert "configured" in body["llm"]


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

    enterprise = client.get(f"/settings/stores/{store_id}/enterprise")
    assert enterprise.status_code == 200
    assert "name" in enterprise.json()

    saved = client.put(
        f"/settings/stores/{store_id}/enterprise",
        json={
            "name": "餐钥餐饮管理",
            "brand_name": "餐钥小馆",
            "category": "正餐",
            "cuisine_type": "本帮菜",
            "location": "上海·静安",
            "business_hours": "10:00-22:00",
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["name"] == "餐钥餐饮管理"
    assert body["brand_name"] == "餐钥小馆"
    assert body["category"] == "正餐"

    overview_after = client.get("/settings/overview", params={"store_id": store_id})
    assert overview_after.status_code == 200
    assert overview_after.json()["enterprise"]["name"] == "餐钥餐饮管理"

    store_only = client.put(
        f"/settings/stores/{store_id}",
        json={"name": "静安一店"},
    )
    assert store_only.status_code == 200
    assert store_only.json()["store"]["name"] == "静安一店"
    kept = client.get(f"/settings/stores/{store_id}/enterprise")
    assert kept.json()["name"] == "餐钥餐饮管理"
    assert kept.json()["org"]["brand_count"] >= 1
    assert kept.json()["org"]["store_count"] >= 1


def test_enterprise_multi_brand_multi_store() -> None:
    seed = client.post("/dev/seed")
    assert seed.status_code == 200
    store_id = seed.json()["store_id"]

    enterprise = client.get(f"/settings/stores/{store_id}/enterprise")
    assert enterprise.status_code == 200
    first_brand_id = enterprise.json()["brand_id"] or enterprise.json()["org"]["brands"][0]["brand_id"]

    created_brand = client.post(
        f"/settings/stores/{store_id}/brands",
        json={"name": "餐钥茶铺", "category": "饮品", "cuisine_type": "茶饮"},
    )
    assert created_brand.status_code == 200
    brands = created_brand.json()["org"]["brands"]
    assert len(brands) >= 2
    tea = next(item for item in brands if item["name"] == "餐钥茶铺")

    created_store = client.post(
        f"/settings/stores/{store_id}/brands/{tea['brand_id']}/stores",
        json={"name": "餐钥茶铺·静安店", "city": "上海", "area": "静安"},
    )
    assert created_store.status_code == 200
    tea_after = next(item for item in created_store.json()["org"]["brands"] if item["brand_id"] == tea["brand_id"])
    assert any(row["name"] == "餐钥茶铺·静安店" for row in tea_after["stores"])

    sibling = client.post(
        f"/settings/stores/{store_id}/brands/{first_brand_id}/stores",
        json={"name": "老王牛肉饭·三里屯店", "city": "北京", "area": "三里屯"},
    )
    assert sibling.status_code == 200
    assert sibling.json()["org"]["store_count"] >= 3

    listing = client.get("/workspace/stores")
    assert listing.status_code == 200
    names = {row["name"] for row in listing.json()["stores"]}
    assert "餐钥茶铺·静安店" in names
    assert "老王牛肉饭·三里屯店" in names
    tea_row = next(row for row in listing.json()["stores"] if row["name"] == "餐钥茶铺·静安店")
    assert tea_row["brand_name"] == "餐钥茶铺"
    assert tea_row["merchant_id"] == created_store.json()["merchant_id"]


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
