"""Commercial OS V1：报价 / 政策 / 头像账单。演示环境直接入账，不走真实支付。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.entities import Store
from app.services.commercial import customer_bill, partner_year_one_story
from app.services.commercial.ai_ledger import budget_state, charge_ai, plan_token_cost_cny
from app.services.commercial.board import (
    activate_by_bank_transfer,
    list_manual_payment_requests,
    merchant_board,
    request_manual_payment,
    review_manual_payment,
    subscribe_cycle,
    topup_wallet,
)
from app.services.commercial.model_router import route_model
from app.services.commercial.north_star import company_north_star
from app.services.commercial.policy import policy_snapshot
from app.services.commercial.pricing import quote_subscription

router = APIRouter()


class QuoteRequest(BaseModel):
    active_stores: int = Field(ge=1, le=100000)
    billing_cycle: str = "monthly"
    ai_actual_cny: Optional[float] = None


class PartnerRateRequest(BaseModel):
    new_qualified_stores: int = Field(ge=0, le=100000)
    ninety_day_qualified_stores: int = Field(default=0, ge=0, le=100000)
    annual_subscription_cny: float = 3000.0


class RouteRequest(BaseModel):
    purpose: str
    budget_state: str = "normal"
    lane: str = "operating"


class SubscribeRequest(BaseModel):
    billing_cycle: str = "monthly"


class WalletTopupRequest(BaseModel):
    amount_cny: float = Field(gt=0, le=100000)


class ActivateRequest(BaseModel):
    kind: str = "subscription"
    billing_cycle: str = "monthly"
    amount_cny: float = Field(default=300, gt=0, le=100000)
    operator: str = "ops"
    transfer_note: str = ""


class ManualPaymentRequestInput(BaseModel):
    kind: str = "subscription"
    billing_cycle: str = "monthly"
    amount_cny: float = Field(default=0, ge=0, le=100000)
    payer_name: str = ""
    transfer_note: str = Field(min_length=1, max_length=120)
    evidence_url: str = ""


class ManualPaymentReviewInput(BaseModel):
    approved: bool
    operator: str = Field(default="ops", min_length=1, max_length=64)
    review_note: str = ""


def _load_store(db: Session, store_id: str) -> Store:
    store = db.execute(select(Store).where(Store.id == store_id)).scalar_one_or_none()
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    return store


@router.get("/commercial/policy")
def get_commercial_policy():
    return policy_snapshot()


@router.get("/commercial/north-star")
def get_commercial_north_star(db: Session = Depends(get_db)):
    return company_north_star(db)


@router.post("/commercial/quote")
def post_commercial_quote(request: QuoteRequest):
    return customer_bill(
        active_stores=request.active_stores,
        billing_cycle=request.billing_cycle,
        ai_actual_cny=request.ai_actual_cny,
    )


@router.post("/commercial/subscription-quote")
def post_subscription_quote(request: QuoteRequest):
    return quote_subscription(request.active_stores, request.billing_cycle).as_dict()


@router.post("/commercial/ai-charge")
def post_ai_charge(actual_cost_cny: float, store_count: int = 1):
    return {
        "charge": charge_ai(actual_cost_cny).as_dict(),
        "budget": budget_state(actual_cost_cny, store_count).as_dict(),
        "plan_4_5m": plan_token_cost_cny(),
    }


@router.post("/commercial/partner-year")
def post_partner_year(request: PartnerRateRequest):
    return partner_year_one_story(
        request.new_qualified_stores,
        request.annual_subscription_cny,
        ninety_day_qualified_stores=request.ninety_day_qualified_stores,
    )


@router.post("/commercial/route-model")
def post_route_model(request: RouteRequest):
    return {
        "purpose": request.purpose,
        "tier": route_model(request.purpose, budget_state=request.budget_state, lane=request.lane),
    }


@router.get("/stores/{store_id}/commercial/board")
def get_store_commercial_board(store_id: str, db: Session = Depends(get_db)):
    return merchant_board(db, _load_store(db, store_id))


@router.post("/stores/{store_id}/commercial/subscribe")
def post_store_commercial_subscribe(
    store_id: str,
    request: SubscribeRequest,
    db: Session = Depends(get_db),
):
    try:
        payload = subscribe_cycle(db, _load_store(db, store_id), request.billing_cycle)
        db.commit()
        return payload
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/stores/{store_id}/commercial/wallet/topup")
def post_store_wallet_topup(
    store_id: str,
    request: WalletTopupRequest,
    db: Session = Depends(get_db),
):
    try:
        payload = topup_wallet(db, _load_store(db, store_id), request.amount_cny)
        db.commit()
        return payload
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/stores/{store_id}/commercial/activate")
def post_store_commercial_activate(
    store_id: str,
    request: ActivateRequest,
    db: Session = Depends(get_db),
):
    try:
        payload = activate_by_bank_transfer(
            db,
            _load_store(db, store_id),
            kind=request.kind,
            billing_cycle=request.billing_cycle,
            amount_cny=request.amount_cny,
            operator=request.operator,
            transfer_note=request.transfer_note,
        )
        db.commit()
        return payload
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/stores/{store_id}/commercial/manual-payment")
def post_store_manual_payment(
    store_id: str,
    request: ManualPaymentRequestInput,
    db: Session = Depends(get_db),
):
    try:
        row = request_manual_payment(
            db,
            _load_store(db, store_id),
            kind=request.kind,
            billing_cycle=request.billing_cycle,
            amount_cny=request.amount_cny,
            payer_name=request.payer_name,
            transfer_note=request.transfer_note,
            evidence_url=request.evidence_url,
        )
        db.commit()
        db.refresh(row)
        return {
            "ok": True,
            "request": {
                "id": row.id,
                "store_id": row.store_id,
                "kind": row.kind,
                "billing_cycle": row.billing_cycle,
                "amount_cny": row.amount_cny,
                "status": row.status,
                "transfer_note": row.transfer_note,
                "evidence_url": row.evidence_url or "",
            },
        }
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/commercial/manual-payments")
def get_manual_payment_requests(
    status: str = "pending",
    store_id: str = "",
    db: Session = Depends(get_db),
):
    rows = list_manual_payment_requests(db, status=status, store_id=store_id)
    return {
        "requests": [
            {
                "id": row.id,
                "store_id": row.store_id,
                "merchant_id": row.merchant_id,
                "kind": row.kind,
                "billing_cycle": row.billing_cycle,
                "amount_cny": row.amount_cny,
                "payer_name": row.payer_name or "",
                "transfer_note": row.transfer_note,
                "evidence_url": row.evidence_url or "",
                "status": row.status,
                "reviewed_by": row.reviewed_by or "",
                "review_note": row.review_note or "",
                "created_at": row.created_at.isoformat() if row.created_at else "",
            }
            for row in rows
        ]
    }


@router.post("/commercial/manual-payments/{request_id}/review")
def post_manual_payment_review(
    request_id: str,
    request: ManualPaymentReviewInput,
    db: Session = Depends(get_db),
):
    try:
        payload = review_manual_payment(
            db,
            request_id,
            approved=request.approved,
            operator=request.operator,
            review_note=request.review_note,
        )
        db.commit()
        return payload
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
