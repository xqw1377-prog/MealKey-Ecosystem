import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes_dev import seed_demo
from app.db.base import Base
from app.models.entities import MenuItem, MenuItemVersion
from app.models.ohre import Recommendation
from app.services.recommendation_executor import execute_recommendation_domain


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_execute_change_title_writes_menu_version():
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    item = db.execute(select(MenuItem).where(MenuItem.store_id == store_id).limit(1)).scalar_one()
    old_version_id = item.current_version_id

    rec = Recommendation(
        store_id=store_id,
        scope="item",
        object_ref=f"item:{item.id}",
        action_type="change_title",
        expected_metric="ctr",
        status="adopted",
        content_json=json.dumps(
            {
                "source": "product_agent",
                "product_suggestion": {
                    "action_type": "change_title",
                    "title": "新标题",
                    "generated_content": {"suggested_title": "黑椒牛肉饭·份量升级"},
                },
            },
            ensure_ascii=False,
        ),
    )
    db.add(rec)
    db.commit()

    result = execute_recommendation_domain(db, rec)
    db.commit()
    db.refresh(item)

    assert result["applied"] is True
    assert result["mode"] == "in_system"
    assert item.current_version_id != old_version_id
    version = db.get(MenuItemVersion, item.current_version_id)
    assert version is not None
    assert version.name == "黑椒牛肉饭·份量升级"


def test_execute_matrix_action_awaits_platform():
    db = _session()
    seeded = seed_demo(db)
    rec = Recommendation(
        store_id=seeded["store_id"],
        scope="store",
        object_ref="store:x",
        action_type="boost_hero_item_ads",
        expected_metric="orders",
        status="adopted",
        content_json="{}",
    )
    db.add(rec)
    db.commit()
    result = execute_recommendation_domain(db, rec)
    assert result["applied"] is False
    assert result["mode"] == "awaiting_platform"


def test_execute_main_image_writes_version():
    db = _session()
    seeded = seed_demo(db)
    store_id = seeded["store_id"]
    item = db.execute(select(MenuItem).where(MenuItem.store_id == store_id).limit(1)).scalar_one()
    rec = Recommendation(
        store_id=store_id,
        scope="item",
        object_ref=f"item:{item.id}",
        action_type="change_main_image",
        expected_metric="ctr",
        status="adopted",
        content_json=json.dumps(
            {
                "product_suggestion": {
                    "action_type": "change_main_image",
                    "generated_content": {"visual_brief": "近景主菜"},
                }
            },
            ensure_ascii=False,
        ),
    )
    db.add(rec)
    db.commit()
    result = execute_recommendation_domain(db, rec)
    db.commit()
    db.refresh(item)
    assert result["applied"] is True
    version = db.get(MenuItemVersion, item.current_version_id)
    assert version is not None
    assert version.image_url and "mealkey://optimized-main-image" in version.image_url
