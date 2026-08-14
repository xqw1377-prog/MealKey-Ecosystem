"""头像账单：经营服务费 + AI 算力储值。演示环境直接入账，不走真实支付。"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.commercial import (
    AIComputeInvoice,
    AIUsageLedger,
    AIWallet,
    AIWalletTopup,
    ManualPaymentRequest,
    PricingContract,
    StoreLicense,
    Subscription,
)
from app.models.entities import Store
from app.services.commercial.policy import POSITIONING_LINE, SLA_PROMISES, WALLET_LOW_CNY, WALLET_TOPUP_TIERS_CNY
from app.services.commercial.pricing import normalize_cycle, quote_subscription


def _add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, monthrange(year, month)[1])
    return date(year, month, day)


def _active_store_count(db: Session, merchant_id: str) -> int:
    count = db.execute(
        select(func.count())
        .select_from(Store)
        .where(Store.merchant_id == merchant_id, Store.status == "active")
    ).scalar_one()
    return max(int(count or 0), 1)


def _ensure_wallet(db: Session, merchant_id: str) -> AIWallet:
    wallet = db.execute(select(AIWallet).where(AIWallet.merchant_id == merchant_id)).scalar_one_or_none()
    if wallet:
        return wallet
    wallet = AIWallet(merchant_id=merchant_id, balance_cny=0)
    db.add(wallet)
    db.flush()
    return wallet


def _month_used_cny(db: Session, merchant_id: str, period_month: str) -> float:
    invoice = db.execute(
        select(AIComputeInvoice).where(
            AIComputeInvoice.merchant_id == merchant_id,
            AIComputeInvoice.period_month == period_month,
        )
    ).scalar_one_or_none()
    if invoice:
        return round(float(invoice.billed_cny or 0), 2)
    total = db.execute(
        select(func.coalesce(func.sum(AIUsageLedger.billed_cny), 0)).where(
            AIUsageLedger.merchant_id == merchant_id,
            AIUsageLedger.period_month == period_month,
        )
    ).scalar_one()
    return round(float(total or 0), 2)


def _current_contract(db: Session, merchant_id: str) -> PricingContract | None:
    return db.execute(
        select(PricingContract)
        .where(PricingContract.merchant_id == merchant_id, PricingContract.status == "active")
        .order_by(PricingContract.created_at.desc())
    ).scalars().first()


def _latest_subscription(db: Session, merchant_id: str) -> Subscription | None:
    return db.execute(
        select(Subscription)
        .where(Subscription.merchant_id == merchant_id)
        .order_by(Subscription.created_at.desc())
    ).scalars().first()


def wallet_alert(*, balance_cny: float, month_used_cny: float, ever_topped_up: bool) -> dict:
    """客户只看人民币。empty/low 时给出充值入口，不提 Token。"""
    balance = round(max(float(balance_cny or 0), 0.0), 2)
    used = round(max(float(month_used_cny or 0), 0.0), 2)
    if balance <= 0:
        status = "empty"
        title = "AI 算力余额不足"
        message = "当前储值已用完，充值后店长才能继续深度分析。" if (used > 0 or ever_topped_up) else "先充一档算力，店长做海报和深度分析才不会中断。"
    elif balance < WALLET_LOW_CNY:
        status = "low"
        title = "AI 算力快用完了"
        message = f"还剩 ¥{balance:.0f}，建议先充一档，避免分析中断。"
    else:
        status = "ok"
        title = ""
        message = ""
    show_home = status == "low" or (status == "empty" and (used > 0 or ever_topped_up))
    return {
        "status": status,
        "title": title,
        "message": message,
        "cta": "去充值",
        "purchase_path": "avatar_wallet",
        "show_home_banner": show_home,
        "low_cny": WALLET_LOW_CNY,
    }


def _wallet_payload(db: Session, merchant_id: str) -> dict:
    period_month = datetime.now(timezone.utc).strftime("%Y-%m")
    wallet = db.execute(select(AIWallet).where(AIWallet.merchant_id == merchant_id)).scalar_one_or_none()
    balance = round(float(wallet.balance_cny or 0), 2) if wallet else 0.0
    used = _month_used_cny(db, merchant_id, period_month)
    ever = (
        db.execute(
            select(func.count())
            .select_from(AIWalletTopup)
            .where(AIWalletTopup.merchant_id == merchant_id)
        ).scalar_one()
        or 0
    ) > 0
    alert = wallet_alert(balance_cny=balance, month_used_cny=used, ever_topped_up=ever)
    return {
        "balance_cny": balance,
        "month_used_cny": used,
        "period_month": period_month,
        "topup_tiers_cny": list(WALLET_TOPUP_TIERS_CNY),
        "alert": alert,
    }


def merchant_board(db: Session, store: Store) -> dict:
    merchant_id = store.merchant_id
    stores = _active_store_count(db, merchant_id)
    quotes = {
        cycle: quote_subscription(stores, cycle).as_dict()
        for cycle in ("monthly", "quarterly", "annual")
    }
    contract = _current_contract(db, merchant_id)
    subscription = _latest_subscription(db, merchant_id)
    license_row = db.execute(select(StoreLicense).where(StoreLicense.store_id == store.id)).scalar_one_or_none()
    cycle = normalize_cycle((contract or subscription).billing_cycle if (contract or subscription) else "monthly")
    current_quote = quotes[cycle]
    pending_requests = db.execute(
        select(func.count())
        .select_from(ManualPaymentRequest)
        .where(
            ManualPaymentRequest.store_id == store.id,
            ManualPaymentRequest.status == "pending",
        )
    ).scalar_one()
    return {
        "store_id": store.id,
        "merchant_id": merchant_id,
        "store_name": store.name,
        "active_stores": stores,
        "current": {
            "billing_cycle": cycle,
            "status": getattr(license_row, "status", None) or getattr(subscription, "status", None) or "trial",
            "period_start": subscription.period_start.isoformat() if subscription else None,
            "period_end": subscription.period_end.isoformat() if subscription else None,
            "equiv_monthly_cny": (
                float(contract.equiv_monthly_cny)
                if contract is not None
                else current_quote["equiv_monthly_cny"]
            ),
            "billed_cny": (
                float(subscription.collected_amount_cny)
                if subscription is not None
                else current_quote["billed_cny"]
            ),
        },
        "quotes": quotes,
        "wallet": _wallet_payload(db, merchant_id),
        "customer_sees": ["经营服务费", "AI算力储值"],
        "customer_does_not_see": ["token", "agent套餐", "功能等级", "会员等级"],
        "promise": {
            "positioning": POSITIONING_LINE,
            "sells": "持续经营责任",
            "does_not_sell": ["AI分析", "AI诊断", "AI报表", "AI聊天"],
            "sla": list(SLA_PROMISES),
        },
        "billing": _billing_channel(),
        "manual_reconciliation": {
            "pending_requests": int(pending_requests or 0),
            "submission_hint": "商家提交转账备注和凭证后，由运营审核开通。",
        },
        "demo_note": (
            "演示环境直接入账，不走真实支付。"
            if settings.is_dev
            else "对公转账后由运营手工开通。种子客户不走微信自动扣费。"
        ),
    }


def _billing_channel() -> dict:
    from app.services.seed_launch import transfer_instructions

    return transfer_instructions()


def activate_by_bank_transfer(
    db: Session,
    store: Store,
    *,
    kind: str = "subscription",
    billing_cycle: str = "monthly",
    amount_cny: float = 300.0,
    operator: str = "ops",
    transfer_note: str = "",
) -> dict:
    note = str(transfer_note or "").strip()
    if not note:
        raise ValueError("手工开通必须填写转账备注（店名或订单号）")
    kind_key = str(kind or "subscription").strip().lower()
    if kind_key == "wallet":
        return topup_wallet(
            db,
            store,
            amount_cny,
            payment_method="bank_transfer",
            operator=operator,
            transfer_note=note,
        )
    return subscribe_cycle(
        db,
        store,
        billing_cycle,
        payment_method="bank_transfer",
        operator=operator,
        transfer_note=note,
    )


def subscribe_cycle(
    db: Session,
    store: Store,
    billing_cycle: str,
    *,
    payment_method: str = "demo_direct",
    operator: str = "",
    transfer_note: str = "",
) -> dict:
    method = (payment_method or "demo_direct").strip().lower()
    if method not in {"demo_direct", "bank_transfer"}:
        raise ValueError("不支持的收款方式")
    if method == "demo_direct" and not settings.is_dev:
        raise ValueError("生产环境不支持演示入账。请对公转账后由运营手工开通。")

    cycle = normalize_cycle(billing_cycle)
    merchant_id = store.merchant_id
    stores = _active_store_count(db, merchant_id)
    quote = quote_subscription(stores, cycle)
    if quote.needs_approval:
        raise ValueError("等效月价低于红线，需人工审批")

    for row in db.execute(
        select(PricingContract).where(PricingContract.merchant_id == merchant_id, PricingContract.status == "active")
    ).scalars():
        row.status = "superseded"

    contract = PricingContract(
        merchant_id=merchant_id,
        billing_cycle=cycle,
        active_store_count=stores,
        unit_monthly_cny=quote.unit_monthly_cny,
        unit_annual_cny=quote.unit_annual_cny,
        equiv_monthly_cny=quote.equiv_monthly_cny,
        needs_approval=False,
        approved_by=(operator or None) if method == "bank_transfer" else None,
        status="active",
    )
    db.add(contract)
    db.flush()

    start = date.today()
    subscription = Subscription(
        merchant_id=merchant_id,
        contract_id=contract.id,
        period_start=start,
        period_end=_add_months(start, quote.used_months),
        billing_cycle=cycle,
        store_count=stores,
        base_amount_cny=quote.billed_cny,
        collected_amount_cny=quote.billed_cny,
        status="collected",
    )
    db.add(subscription)

    license_row = db.execute(select(StoreLicense).where(StoreLicense.store_id == store.id)).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if license_row is None:
        license_row = StoreLicense(
            merchant_id=merchant_id,
            store_id=store.id,
            kind="owned",
            status="paid",
            first_paid_at=now,
            activated_at=now,
        )
        db.add(license_row)
    else:
        license_row.status = "paid"
        if license_row.first_paid_at is None:
            license_row.first_paid_at = now
        if license_row.activated_at is None:
            license_row.activated_at = now

    db.flush()
    return merchant_board(db, store)


def topup_wallet(
    db: Session,
    store: Store,
    amount_cny: float,
    *,
    payment_method: str = "demo_direct",
    operator: str = "",
    transfer_note: str = "",
) -> dict:
    method = (payment_method or "demo_direct").strip().lower()
    if method not in {"demo_direct", "bank_transfer"}:
        raise ValueError("不支持的收款方式")
    if method == "demo_direct" and not settings.is_dev:
        raise ValueError("生产环境不支持演示入账。请对公转账后由运营手工开通。")
    amount = round(float(amount_cny or 0), 2)
    allowed = {round(float(tier), 2) for tier in WALLET_TOPUP_TIERS_CNY}
    if amount not in allowed:
        raise ValueError("请选择系统提供的储值档位")
    wallet = _ensure_wallet(db, store.merchant_id)
    wallet.balance_cny = round(float(wallet.balance_cny or 0) + amount, 2)
    db.add(
        AIWalletTopup(
            merchant_id=store.merchant_id,
            wallet_id=wallet.id,
            amount_cny=amount,
            status="collected",
            note=(
                "demo_direct_credit"
                if method == "demo_direct"
                else f"bank_transfer:{operator}:{transfer_note}"
            ),
        )
    )
    db.flush()
    return merchant_board(db, store)


def request_manual_payment(
    db: Session,
    store: Store,
    *,
    kind: str,
    billing_cycle: str = "monthly",
    amount_cny: float = 0,
    payer_name: str = "",
    transfer_note: str,
    evidence_url: str = "",
) -> ManualPaymentRequest:
    note = str(transfer_note or "").strip()
    if not note:
        raise ValueError("请填写转账备注，便于核销。")
    kind_key = str(kind or "subscription").strip().lower()
    if kind_key not in {"subscription", "wallet"}:
        raise ValueError("不支持的申请类型。")
    amount = round(float(amount_cny or 0), 2)
    if kind_key == "subscription" and amount <= 0:
        quote = quote_subscription(_active_store_count(db, store.merchant_id), billing_cycle)
        amount = quote.billed_cny
    if kind_key == "wallet":
        allowed = {round(float(tier), 2) for tier in WALLET_TOPUP_TIERS_CNY}
        if amount not in allowed:
            raise ValueError("请选择系统提供的储值档位。")
    row = ManualPaymentRequest(
        merchant_id=store.merchant_id,
        store_id=store.id,
        kind=kind_key,
        billing_cycle=normalize_cycle(billing_cycle),
        amount_cny=amount,
        payer_name=str(payer_name or "").strip() or None,
        transfer_note=note[:120],
        evidence_url=str(evidence_url or "").strip() or None,
        status="pending",
    )
    db.add(row)
    db.flush()
    return row


def list_manual_payment_requests(
    db: Session,
    *,
    status: str = "pending",
    store_id: str = "",
) -> list[ManualPaymentRequest]:
    query = select(ManualPaymentRequest).order_by(ManualPaymentRequest.created_at.desc())
    if status:
        query = query.where(ManualPaymentRequest.status == status)
    if store_id:
        query = query.where(ManualPaymentRequest.store_id == store_id)
    return db.execute(query).scalars().all()


def review_manual_payment(
    db: Session,
    request_id: str,
    *,
    approved: bool,
    operator: str,
    review_note: str = "",
) -> dict:
    row = db.get(ManualPaymentRequest, request_id)
    if row is None:
        raise ValueError("核销申请不存在。")
    if row.status != "pending":
        raise ValueError("该核销申请已经处理过了。")
    store = db.get(Store, row.store_id)
    if store is None:
        raise ValueError("门店不存在。")
    row.reviewed_by = str(operator or "").strip() or "ops"
    row.reviewed_at = datetime.now(timezone.utc)
    row.review_note = str(review_note or "").strip() or None
    if not approved:
        row.status = "rejected"
        db.add(row)
        db.flush()
        return {"request_id": row.id, "status": row.status}
    row.status = "approved"
    if row.kind == "wallet":
        board = activate_by_bank_transfer(
            db,
            store,
            kind="wallet",
            amount_cny=row.amount_cny,
            operator=row.reviewed_by,
            transfer_note=row.transfer_note,
        )
    else:
        board = activate_by_bank_transfer(
            db,
            store,
            kind="subscription",
            billing_cycle=row.billing_cycle,
            operator=row.reviewed_by,
            transfer_note=row.transfer_note,
        )
    current = board.get("current") if isinstance(board, dict) else {}
    row.applied_ref = str(current.get("period_end") or row.transfer_note)[:36] if current else row.transfer_note[:36]
    db.add(row)
    db.flush()
    return {"request_id": row.id, "status": row.status, "board": board}
