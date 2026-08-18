from app.schemas.incremental_result import (
    IncrementalResult,
    RESULT_LAYER_RANK_WEIGHT,
    TreatmentSpec,
    may_authorize_action,
    may_influence_candidate_ranking,
)


def _result(grade: str) -> IncrementalResult:
    return IncrementalResult(
        experiment_id="e1",
        store_id="s1",
        action_type="coupon",
        treatment=TreatmentSpec(treatment="coupon_5"),
        estimated_ate=0.08,
        evidence_grade=grade,  # type: ignore[arg-type]
    )


def test_uplift_never_authorizes() -> None:
    for grade in ("L0_RESEARCH", "L1_STORE_CONTRAST", "L2_CROSS_STORE", "L3_PROFIT_VERIFIED"):
        assert may_authorize_action(_result(grade)) is False


def test_result_layers_have_distinct_rank_weights() -> None:
    assert RESULT_LAYER_RANK_WEIGHT["observed"] < RESULT_LAYER_RANK_WEIGHT["attributed"]
    assert RESULT_LAYER_RANK_WEIGHT["attributed"] < RESULT_LAYER_RANK_WEIGHT["incremental"]


def test_l0_cannot_rank_and_l2_can() -> None:
    assert may_influence_candidate_ranking(_result("L0_RESEARCH")) is False
    assert may_influence_candidate_ranking(_result("L1_STORE_CONTRAST")) is False
    assert may_influence_candidate_ranking(_result("L2_CROSS_STORE")) is True
