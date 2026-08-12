from datetime import datetime

from app.models.operating_decision import OperatingDecision
from app.models.runtime_v1 import (
    BusinessEventRecord,
    DailyOperatingPlanRecord,
    ExperimentResultRecord,
    MerchantContextItemRecord,
    OperatingActionRecord,
    RuntimeEventRecord,
    SignalRecord,
    StoreStateSnapshotRecord,
)
from app.schemas.content_engine import OperatingDecisionObject
from app.schemas.runtime import DailyOperatingPlan
from app.schemas.runtime_api import DailyPlanResponse, WorkspaceRuntimeResponse
from app.schemas.runtime_event import (
    ArbitrationQueueEntry,
    CandidateODOEnvelope,
    RuntimeEventEnvelope,
    RuntimeFeedResponse,
    RuntimeQueueResponse,
    RuntimeSignalEnvelope,
)
from app.schemas.runtime_objects import (
    ActionObject,
    BusinessEventObject,
    ExperimentObject,
    MerchantContextItem,
    ResultObject,
    RuntimeChainObject,
    SignalObject,
    StoreStateSnapshot,
    StrategyMemoryObject,
    WorkThreadObject,
)


def test_runtime_signal_and_event_contracts_validate() -> None:
    observed_at = datetime.now()
    signal = RuntimeSignalEnvelope(
        id="sig_1",
        store_id="store_1",
        state="peak_protect",
        node="lunch_protect",
        source="platform",
        kind="hero_sku_sold_out",
        payload={"sku_id": "sku_1"},
        observed_at=observed_at,
    )
    event = RuntimeEventEnvelope(
        id="evt_1",
        store_id="store_1",
        state="peak_protect",
        node="lunch_protect",
        trigger_reason="ANOMALY",
        domain="PRODUCT",
        title="黑椒牛肉饭提前售罄",
        occurred_at=observed_at,
    )
    assert signal.state == "peak_protect"
    assert event.trigger_reason == "ANOMALY"
    assert event.domain == "PRODUCT"


def test_candidate_odo_and_queue_contracts_validate() -> None:
    odo = OperatingDecisionObject(
        reason="ANOMALY",
        domain="PRODUCT",
        execution_mode="ASK_INFORMATION",
    )
    candidate = CandidateODOEnvelope(
        id="odo_1",
        state="peak_protect",
        node="lunch_protect",
        trigger_reason="ANOMALY",
        domain="PRODUCT",
        odo=odo,
        generated_at=datetime.now(),
    )
    queue = RuntimeQueueResponse(
        store_id="store_1",
        runtime_state="peak_protect",
        items=[
            ArbitrationQueueEntry(
                candidate_odo_id="odo_1",
                runtime_state="peak_protect",
                priority_score=88.3,
                decision="ASK_INFORMATION",
                interrupt_owner=True,
            )
        ],
    )
    assert candidate.odo.execution_mode == "ASK_INFORMATION"
    assert queue.items[0].interrupt_owner is True


def test_runtime_api_contracts_validate() -> None:
    plan = DailyOperatingPlan(date="2026-08-12", current_runtime_state="pre_peak_decision", current_meal_period="lunch")
    daily = DailyPlanResponse(plan=plan, runtime_state="pre_peak_decision")
    workspace = WorkspaceRuntimeResponse.model_validate(
        {
            "store": {"store_id": "store_1", "store_name": "老王牛肉饭", "runtime_state": "pre_peak_decision"},
            "left": {"need_you": [], "active": [], "waiting": [], "completed": [], "opportunities": [], "active_goal": None, "threads": []},
            "center": {"active_thread_id": None, "guide": {}, "principle": "系统负责发现所有事情"},
            "right": {"proactive_feed": [], "filtered_count": 0},
            "meta": {"candidates_total": 0, "filtered_noop_count": 0, "mealkey_score": None, "operation_score": None},
        }
    )
    assert daily.runtime_state == "pre_peak_decision"
    assert workspace.store.runtime_state == "pre_peak_decision"


def test_runtime_models_expose_v1_columns() -> None:
    assert hasattr(StoreStateSnapshotRecord, "state_json")
    assert hasattr(MerchantContextItemRecord, "value_json")
    assert hasattr(SignalRecord, "signal_type")
    assert hasattr(BusinessEventRecord, "event_type")
    assert hasattr(DailyOperatingPlanRecord, "plan_date")
    assert hasattr(RuntimeEventRecord, "trigger_reason")
    assert hasattr(OperatingActionRecord, "parameters_json")
    assert hasattr(ExperimentResultRecord, "primary_result_json")
    assert hasattr(RuntimeEventRecord, "source_odo_id")
    assert hasattr(OperatingDecision, "runtime_state")
    assert hasattr(OperatingDecision, "analysis_node")
    assert hasattr(OperatingDecision, "source_event_id")


def test_runtime_feed_response_contract_validates() -> None:
    feed = RuntimeFeedResponse(store_id="store_1", runtime_state="pre_peak_decision", events=[])
    assert feed.runtime_state == "pre_peak_decision"


def test_runtime_object_contracts_validate() -> None:
    snapshot = StoreStateSnapshot(store_id="store_1", snapshot_at=datetime.now())
    context = MerchantContextItem(key="ads_auto_budget_limit", value_json={"daily_cny": 300})
    signal = SignalObject(id="sig_1", type="PRODUCT_METRIC_CHANGED", store_id="store_1", occurred_at=datetime.now())
    event = BusinessEventObject(event_id="evt_1", event_type="HERO_SKU_CTR_DROP", domain="PRODUCT", store_id="store_1")
    thread = WorkThreadObject(id="wt_1", title="黑椒牛肉饭进入商圈 Top3")
    action = ActionObject(id="act_1", type="ADJUST_AD_BUDGET")
    experiment = ExperimentObject(experiment_id="exp_1")
    result = ResultObject(experiment_id="exp_1", outcome="SUCCESS")
    memory = StrategyMemoryObject(strategy="portion_emphasis_main_image")
    chain = RuntimeChainObject(
        store_state=snapshot,
        merchant_context=[context],
        signals=[signal],
        events=[event],
        work_threads=[thread],
        actions=[action],
        experiments=[experiment],
        results=[result],
        memories=[memory],
    )
    assert chain.store_state is not None
    assert chain.events[0].event_type == "HERO_SKU_CTR_DROP"
