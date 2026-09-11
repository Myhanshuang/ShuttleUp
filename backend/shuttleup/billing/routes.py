import hashlib
import json
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..activities.service import activity_dto, emit, participant_for, require_host, require_member
from ..auth.service import require_csrf, require_user
from ..common import short_code
from ..db import get_db
from ..models import Activity, BillRevision, Expense, ExpenseShare, OperationKey, Participant, PaymentClaim, now_ms
from .calculator import AllocatedExpense, ConfirmedPayment, ParticipantRef, allocate_equal, allocate_exact, allocate_refund, calculate_balances, simplify_transfers

router = APIRouter(tags=["billing"])


class ShareInput(BaseModel):
    participant_id: str
    exact_amount_cents: int | None = Field(default=None, ge=0)


class ExpenseCreate(BaseModel):
    kind: str = Field(pattern="^(venue|shuttle|extra)$")
    description: str = Field(min_length=1, max_length=120)
    amount_cents: int = Field(gt=0, le=100_000_000)
    payer_participant_id: str
    split_mode: str = Field(default="equal", pattern="^(equal|exact)$")
    split_scope: str = Field(default="attendees", pattern="^(attendees|selected)$")
    shares: list[ShareInput] = Field(default_factory=list)
    quantity: int | None = Field(default=None, gt=0)
    unit_price_cents: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def exact_total(self):
        if self.split_mode == "exact" and sum(s.exact_amount_cents or 0 for s in self.shares) != self.amount_cents: raise ValueError("指定金额之和必须等于费用")
        if self.split_scope == "selected" and not self.shares: raise ValueError("请选择承担人")
        return self


class RefundCreate(BaseModel):
    amount_cents: int = Field(lt=0, ge=-100_000_000)
    payer_participant_id: str
    allocations: list[ShareInput] = Field(default_factory=list)


class PublishRequest(BaseModel): expected_generation: int
class ReopenRequest(BaseModel): reason: str = Field(min_length=1, max_length=200); expected_generation: int
class ClaimRequest(BaseModel): bill_revision_id: str; transfer_id: str; amount_cents: int = Field(gt=0)


def members(db: Session, activity_id: str) -> list[Participant]:
    return db.scalars(select(Participant).where(Participant.activity_id == activity_id).order_by(Participant.join_order)).all()


def ensure_participant(items: list[Participant], pid: str) -> Participant:
    found = next((p for p in items if p.id == pid), None)
    if not found: raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "费用成员不属于本活动。"})
    return found


def expense_dto(expense: Expense, shares: list[ExpenseShare]):
    return {"id": expense.id, "short_code": expense.short_code, "kind": expense.kind, "description": expense.description, "amount_cents": expense.amount_cents, "payer_participant_id": expense.payer_participant_id, "split_mode": expense.split_mode, "split_scope": expense.split_scope, "quantity": expense.quantity, "unit_price_cents": expense.unit_price_cents, "booking_id": expense.booking_id, "refund_of_id": expense.refund_of_id, "shares": [{"participant_id": s.participant_id, "exact_amount_cents": s.exact_amount_cents} for s in shares], "version": expense.version}


def load_calculation(db: Session, activity: Activity):
    ps = members(db, activity.id); refs = [ParticipantRef(p.id, p.join_order, p.display_name) for p in ps]
    expenses = db.scalars(select(Expense).where(Expense.activity_id == activity.id, Expense.voided_at.is_(None)).order_by(Expense.created_at)).all()
    allocated = []
    for expense in expenses:
        rows = db.scalars(select(ExpenseShare).where(ExpenseShare.expense_id == expense.id)).all()
        if expense.amount_cents < 0:
            allocations = {s.participant_id: s.exact_amount_cents or 0 for s in rows}
        elif expense.split_mode == "exact":
            allocations = allocate_exact(expense.amount_cents, {s.participant_id: s.exact_amount_cents or 0 for s in rows})
        else:
            selected = [ensure_participant(ps, s.participant_id) for s in rows] if rows else [p for p in ps if p.attendance == "present" and p.attendance_verified]
            allocations = allocate_equal(expense.amount_cents, [ParticipantRef(p.id, p.join_order, p.display_name) for p in selected])
        allocated.append(AllocatedExpense(expense.id, expense.payer_participant_id, expense.amount_cents, allocations))
    confirmed = db.scalars(select(PaymentClaim).where(PaymentClaim.activity_id == activity.id, PaymentClaim.status == "confirmed")).all()
    payments = [ConfirmedPayment(p.id, p.from_participant_id, p.to_participant_id, p.amount_cents) for p in confirmed]
    balances = calculate_balances(refs, allocated, payments)
    transfers = simplify_transfers(balances, refs)
    for transfer in transfers:
        transfer["id"] = str(uuid.uuid4()); transfer["short_code"] = short_code()
    snapshot = {"schema_version": 1, "currency": "CNY", "participant_snapshots": [{"id": p.id, "name": p.name, "join_order": p.join_order} for p in refs], "expense_snapshots": [{"id": e.id, "amount_cents": e.amount_cents, "payer_participant_id": e.payer_id, "allocations": [{"participant_id": pid, "amount_cents": amount} for pid, amount in e.allocations.items()]} for e in allocated], "confirmed_payment_ids_at_publish": [p.id for p in payments], "balances_at_publish": balances, "transfers": transfers}
    return snapshot


def idempotent(db: Session, scope: str, key: str | None, body: dict):
    if not key: raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "缺少 Idempotency-Key。"})
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    old = db.scalar(select(OperationKey).where(OperationKey.scope == scope, OperationKey.key == key))
    if old and old.request_hash != digest: raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": "相同幂等键对应了不同请求。"})
    return old, digest


@router.get("/activities/{activity_id}/expenses")
async def list_expenses(activity_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db); activity = db.get(Activity, activity_id); require_member(db, activity, user)
    items = db.scalars(select(Expense).where(Expense.activity_id == activity_id, Expense.voided_at.is_(None))).all()
    return {"items": [expense_dto(e, db.scalars(select(ExpenseShare).where(ExpenseShare.expense_id == e.id)).all()) for e in items], "next_cursor": None}


@router.post("/activities/{activity_id}/expenses", status_code=201)
async def create_expense(activity_id: str, body: ExpenseCreate, request: Request, idempotency_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    user = require_user(request, db); require_csrf(request); activity = db.get(Activity, activity_id); mine = require_member(db, activity, user)
    if activity.billing_status != "draft": raise HTTPException(409, detail={"code": "BILL_NOT_DRAFT", "message": "请先重新打开账单再修改费用。"})
    ps = members(db, activity_id); payer = ensure_participant(ps, body.payer_participant_id)
    if payer.id != mine.id and activity.host_user_id != user.id: raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "普通成员只能记录自己垫付的费用。"})
    old, digest = idempotent(db, f"{user.id}:expense.create", idempotency_key, body.model_dump())
    if old: return old.response
    expense = Expense(short_code=short_code(), activity_id=activity_id, created_by=user.id, **body.model_dump(exclude={"shares"}))
    db.add(expense); db.flush()
    for share in body.shares:
        ensure_participant(ps, share.participant_id); db.add(ExpenseShare(expense_id=expense.id, participant_id=share.participant_id, exact_amount_cents=share.exact_amount_cents))
    activity.bill_generation += 1; activity.version += 1; emit(db, "expense.created", activity=activity, actor=user, payload={"expense_id": expense.id, "bill_generation": activity.bill_generation})
    result = expense_dto(expense, db.scalars(select(ExpenseShare).where(ExpenseShare.expense_id == expense.id)).all())
    db.add(OperationKey(scope=f"{user.id}:expense.create", key=idempotency_key, request_hash=digest, response_status=201, response=result, expires_at=now_ms() + 30*86400000)); db.commit()
    return result


@router.get("/activities/{activity_id}/bill/preview")
async def bill_preview(activity_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db); activity = db.get(Activity, activity_id); require_member(db, activity, user)
    try: snapshot = load_calculation(db, activity)
    except ValueError as error: raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": str(error)})
    return {"bill_generation": activity.bill_generation, "total_cents": sum(e["amount_cents"] for e in snapshot["expense_snapshots"]), **snapshot}


@router.post("/activities/{activity_id}/bill/publish")
async def publish_bill(activity_id: str, body: PublishRequest, request: Request, idempotency_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    user = require_user(request, db); require_csrf(request); activity = db.get(Activity, activity_id); require_member(db, activity, user); require_host(activity, user)
    if activity.status not in ("finished", "cancelled"): raise HTTPException(409, detail={"code": "INVALID_TRANSITION", "message": "活动结束或取消后才能出账。"})
    if activity.billing_status != "draft": raise HTTPException(409, detail={"code": "BILL_NOT_DRAFT", "message": "账单不是编辑状态。"})
    if activity.bill_generation != body.expected_generation: raise HTTPException(409, detail={"code": "VERSION_CONFLICT", "message": "费用刚刚有更新。", "current_version": activity.bill_generation})
    if any(p.attendance == "unknown" or not p.attendance_verified for p in members(db, activity_id)): raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "请先核对所有成员的实际到场状态。"})
    old, digest = idempotent(db, f"{user.id}:bill.publish:{activity_id}", idempotency_key, body.model_dump())
    if old: return old.response
    snapshot = load_calculation(db, activity); number = (db.scalar(select(func.max(BillRevision.revision_no)).where(BillRevision.activity_id == activity_id)) or 0) + 1
    bill = BillRevision(activity_id=activity_id, revision_no=number, source_generation=activity.bill_generation, snapshot=snapshot, total_cents=sum(e["amount_cents"] for e in snapshot["expense_snapshots"]), published_by=user.id)
    db.add(bill); db.flush(); activity.current_bill_id = bill.id; activity.billing_status = "issued" if snapshot["transfers"] else "settled"; activity.version += 1
    emit(db, "bill.published", activity=activity, actor=user, payload={"bill_revision_id": bill.id, "revision_no": number, "total_cents": bill.total_cents})
    result = {"id": bill.id, "revision_no": number, "status": activity.billing_status, "total_cents": bill.total_cents, "snapshot": snapshot}
    db.add(OperationKey(scope=f"{user.id}:bill.publish:{activity_id}", key=idempotency_key, request_hash=digest, response_status=200, response=result, expires_at=now_ms() + 30*86400000)); db.commit(); return result


@router.get("/activities/{activity_id}/bill")
async def get_bill(activity_id: str, request: Request, revision: int | None = None, db: Session = Depends(get_db)):
    user = require_user(request, db); activity = db.get(Activity, activity_id); participant = require_member(db, activity, user)
    query = select(BillRevision).where(BillRevision.activity_id == activity_id)
    if revision is not None: query = query.where(BillRevision.revision_no == revision)
    bill = db.scalar(query.order_by(BillRevision.revision_no.desc()))
    if not bill: raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "账单尚未发布。"})
    claims = db.scalars(select(PaymentClaim).where(PaymentClaim.bill_revision_id == bill.id)).all();balances=dict(bill.snapshot["balances_at_publish"]);at_publish=set(bill.snapshot.get("confirmed_payment_ids_at_publish",[]))
    for claim in claims:
        if claim.status=="confirmed" and claim.id not in at_publish:balances[claim.from_participant_id]+=claim.amount_cents;balances[claim.to_participant_id]-=claim.amount_cents
    transfers=[]
    for transfer in bill.snapshot["transfers"]:
        confirmed=sum(p.amount_cents for p in claims if p.transfer_id==transfer["id"] and p.status=="confirmed");pending=sum(p.amount_cents for p in claims if p.transfer_id==transfer["id"] and p.status=="claimed");transfers.append({**transfer,"confirmed_cents":confirmed,"pending_cents":pending,"remaining_cents":transfer["amount_cents"]-confirmed})
    mine = {"balance_cents": balances.get(participant.id, 0), "outgoing": [t for t in transfers if t["from_participant_id"] == participant.id and t["remaining_cents"]>0], "incoming": [t for t in transfers if t["to_participant_id"] == participant.id and t["remaining_cents"]>0]}
    return {"id": bill.id, "revision_no": bill.revision_no, "status": activity.billing_status, "total_cents": bill.total_cents, "snapshot": bill.snapshot, "my_summary": mine, "payment_claims": [{"id": p.id, "short_code": p.short_code, "transfer_id": p.transfer_id, "amount_cents": p.amount_cents, "status": p.status} for p in claims]}


@router.post("/activities/{activity_id}/payments", status_code=201)
async def claim_payment(activity_id: str, body: ClaimRequest, request: Request, idempotency_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    user = require_user(request, db); require_csrf(request); activity = db.get(Activity, activity_id); participant = require_member(db, activity, user)
    if activity.billing_status != "issued" or activity.current_bill_id != body.bill_revision_id: raise HTTPException(409, detail={"code": "INVALID_TRANSITION", "message": "只能支付当前已发布账单。"})
    bill = db.get(BillRevision, body.bill_revision_id); transfer = next((t for t in bill.snapshot["transfers"] if t["id"] == body.transfer_id), None)
    if not transfer or transfer["from_participant_id"] != participant.id: raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "这不是你的付款任务。"})
    confirmed = db.scalar(select(func.coalesce(func.sum(PaymentClaim.amount_cents), 0)).where(PaymentClaim.bill_revision_id == bill.id, PaymentClaim.transfer_id == body.transfer_id, PaymentClaim.status == "confirmed")) or 0
    if body.amount_cents > transfer["amount_cents"] - confirmed: raise HTTPException(422, detail={"code": "VALIDATION_ERROR", "message": "支付金额超过剩余金额。"})
    if db.scalar(select(PaymentClaim).where(PaymentClaim.bill_revision_id == bill.id, PaymentClaim.transfer_id == body.transfer_id, PaymentClaim.status == "claimed")): raise HTTPException(409, detail={"code": "PAYMENT_PENDING", "message": "已有一笔付款等待确认。"})
    old, digest = idempotent(db, f"{user.id}:payment.claim", idempotency_key, body.model_dump())
    if old: return old.response
    claim = PaymentClaim(short_code=short_code(), activity_id=activity_id, bill_revision_id=bill.id, transfer_id=body.transfer_id, from_participant_id=participant.id, to_participant_id=transfer["to_participant_id"], amount_cents=body.amount_cents)
    db.add(claim); db.flush(); emit(db, "payment.claimed", activity=activity, actor=user, payload={"payment_id": claim.id})
    result = {"id": claim.id, "short_code": claim.short_code, "status": claim.status, "amount_cents": claim.amount_cents}
    db.add(OperationKey(scope=f"{user.id}:payment.claim", key=idempotency_key, request_hash=digest, response_status=201, response=result, expires_at=now_ms()+30*86400000)); db.commit(); return result


@router.post("/activities/{activity_id}/payments/{payment_id}/confirm")
async def confirm_payment(activity_id: str, payment_id: str, request: Request, idempotency_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    user = require_user(request, db); require_csrf(request); activity = db.get(Activity, activity_id); participant = require_member(db, activity, user); claim = db.get(PaymentClaim, payment_id)
    if not claim or claim.activity_id != activity_id: raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "付款声明不存在。"})
    if claim.to_participant_id != participant.id: raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "只有指定收款人可以确认。"})
    old, digest = idempotent(db, f"{user.id}:payment.confirm", idempotency_key, {"payment_id": payment_id})
    if old: return old.response
    if claim.status != "claimed": raise HTTPException(409, detail={"code": "INVALID_TRANSITION", "message": "该付款声明已处理。"})
    claim.status = "confirmed"; claim.confirmed_at = now_ms(); claim.resolved_by_user_id = user.id
    bill = db.get(BillRevision, claim.bill_revision_id); all_paid = True
    for transfer in bill.snapshot["transfers"]:
        amount = db.scalar(select(func.coalesce(func.sum(PaymentClaim.amount_cents), 0)).where(PaymentClaim.bill_revision_id == bill.id, PaymentClaim.transfer_id == transfer["id"], PaymentClaim.status == "confirmed")) or 0
        if amount < transfer["amount_cents"]: all_paid = False
    if all_paid: activity.billing_status = "settled"
    emit(db, "payment.confirmed", activity=activity, actor=user, payload={"payment_id": claim.id})
    if all_paid: emit(db, "bill.settled", activity=activity, actor=user)
    result = {"id": claim.id, "status": claim.status, "bill_status": activity.billing_status}
    db.add(OperationKey(scope=f"{user.id}:payment.confirm", key=idempotency_key, request_hash=digest, response_status=200, response=result, expires_at=now_ms()+30*86400000)); db.commit(); return result


@router.post("/activities/{activity_id}/expenses/{expense_id}/refunds", status_code=201)
async def create_refund(activity_id: str, expense_id: str, body: RefundCreate, request: Request, idempotency_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    user=require_user(request,db); require_csrf(request); activity=db.get(Activity,activity_id); require_member(db,activity,user)
    if activity.billing_status!="draft": raise HTTPException(409,detail={"code":"BILL_NOT_DRAFT","message":"请先重新打开账单再记录退款。"})
    original=db.get(Expense,expense_id)
    if not original or original.activity_id!=activity_id or original.amount_cents<=0: raise HTTPException(404,detail={"code":"NOT_FOUND","message":"原费用不存在。"})
    ps=members(db,activity_id); receiver=ensure_participant(ps,body.payer_participant_id)
    if receiver.user_id!=user.id and activity.host_user_id!=user.id: raise HTTPException(403,detail={"code":"FORBIDDEN","message":"只能记录自己收到的退款。"})
    old,digest=idempotent(db,f"{user.id}:refund.create:{expense_id}",idempotency_key,body.model_dump())
    if old:return old.response
    prior_rows=db.scalars(select(Expense).where(Expense.refund_of_id==expense_id,Expense.voided_at.is_(None))).all(); prior_total=-sum(e.amount_cents for e in prior_rows)
    if prior_total + (-body.amount_cents) > original.amount_cents: raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"累计退款不能超过原费用。"})
    latest=db.scalar(select(BillRevision).where(BillRevision.activity_id==activity_id).order_by(BillRevision.revision_no.desc()))
    original_alloc=None
    if latest:
        snap=next((e for e in latest.snapshot["expense_snapshots"] if e["id"]==expense_id),None)
        if snap: original_alloc={a["participant_id"]:a["amount_cents"] for a in snap["allocations"]}
    if original_alloc is None:
        rows=db.scalars(select(ExpenseShare).where(ExpenseShare.expense_id==expense_id)).all()
        chosen=[ensure_participant(ps,r.participant_id) for r in rows] if rows else [p for p in ps if p.attendance=="present" and p.attendance_verified]
        original_alloc=allocate_exact(original.amount_cents,{r.participant_id:r.exact_amount_cents or 0 for r in rows}) if original.split_mode=="exact" else allocate_equal(original.amount_cents,[ParticipantRef(p.id,p.join_order,p.display_name) for p in chosen])
    already={pid:0 for pid in original_alloc}
    for prior in prior_rows:
        for row in db.scalars(select(ExpenseShare).where(ExpenseShare.expense_id==prior.id)).all(): already[row.participant_id]+=-(row.exact_amount_cents or 0)
    if body.allocations:
        positive={s.participant_id:s.exact_amount_cents or 0 for s in body.allocations}
        if sum(positive.values())!=-body.amount_cents or any(positive.get(pid,0)>original_alloc.get(pid,0)-already.get(pid,0) for pid in positive): raise HTTPException(422,detail={"code":"VALIDATION_ERROR","message":"退款分配超出原承担金额。"})
        allocations={pid:-amount for pid,amount in positive.items()}
    else: allocations=allocate_refund(body.amount_cents,original_alloc,already,{p.id:p.join_order for p in ps})
    refund=Expense(short_code=short_code(),activity_id=activity_id,kind="refund",description=f"退款：{original.description}",amount_cents=body.amount_cents,payer_participant_id=receiver.id,split_mode="exact",split_scope="selected",refund_of_id=original.id,created_by=user.id)
    db.add(refund); db.flush()
    for pid,amount in allocations.items(): db.add(ExpenseShare(expense_id=refund.id,participant_id=pid,exact_amount_cents=amount))
    activity.bill_generation+=1; activity.version+=1; emit(db,"expense.created",activity=activity,actor=user,payload={"expense_id":refund.id,"refund_of_id":original.id}); result={"id":refund.id,"short_code":refund.short_code,"amount_cents":refund.amount_cents,"allocations":allocations}
    db.add(OperationKey(scope=f"{user.id}:refund.create:{expense_id}",key=idempotency_key,request_hash=digest,response_status=201,response=result,expires_at=now_ms()+30*86400000)); db.commit(); return result


@router.delete("/activities/{activity_id}/expenses/{expense_id}", status_code=204)
async def void_expense(activity_id: str, expense_id: str, expected_version: int, request: Request, db: Session=Depends(get_db)):
    user=require_user(request,db); require_csrf(request); activity=db.get(Activity,activity_id); mine=require_member(db,activity,user); expense=db.get(Expense,expense_id)
    if not expense or expense.activity_id!=activity_id: raise HTTPException(404,detail={"code":"NOT_FOUND","message":"费用不存在。"})
    if activity.billing_status!="draft": raise HTTPException(409,detail={"code":"BILL_NOT_DRAFT","message":"请先重新打开账单。"})
    if expense.created_by!=user.id and activity.host_user_id!=user.id: raise HTTPException(403,detail={"code":"FORBIDDEN","message":"不能删除他人记录的费用。"})
    if db.scalar(select(Expense.id).where(Expense.refund_of_id==expense.id,Expense.voided_at.is_(None))): raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"请先处理关联退款。"})
    expense.voided_at=now_ms(); activity.bill_generation+=1; activity.version+=1; emit(db,"expense.voided",activity=activity,actor=user,payload={"expense_id":expense.id}); db.commit()


def resolve_claim(activity_id: str,payment_id: str,target: str,request: Request,db: Session):
    user=require_user(request,db); require_csrf(request); activity=db.get(Activity,activity_id); mine=require_member(db,activity,user); claim=db.get(PaymentClaim,payment_id)
    if not claim or claim.activity_id!=activity_id: raise HTTPException(404,detail={"code":"NOT_FOUND","message":"付款声明不存在。"})
    if target=="withdrawn" and claim.from_participant_id!=mine.id: raise HTTPException(403,detail={"code":"FORBIDDEN","message":"只有付款人可以撤回。"})
    if target=="rejected" and claim.to_participant_id!=mine.id: raise HTTPException(403,detail={"code":"FORBIDDEN","message":"只有收款人可以退回。"})
    if claim.status!="claimed": raise HTTPException(409,detail={"code":"INVALID_TRANSITION","message":"该声明已经处理。"})
    claim.status=target; claim.resolved_by_user_id=user.id; emit(db,f"payment.{target[:-2] if target.endswith('ed') else target}",activity=activity,actor=user,payload={"payment_id":claim.id}); db.commit(); return {"id":claim.id,"status":claim.status}


@router.post("/activities/{activity_id}/payments/{payment_id}/reject")
async def reject_payment(activity_id: str,payment_id: str,request: Request,db: Session=Depends(get_db)): return resolve_claim(activity_id,payment_id,"rejected",request,db)


@router.post("/activities/{activity_id}/payments/{payment_id}/withdraw")
async def withdraw_payment(activity_id: str,payment_id: str,request: Request,db: Session=Depends(get_db)): return resolve_claim(activity_id,payment_id,"withdrawn",request,db)


@router.post("/activities/{activity_id}/bill/reopen")
async def reopen_bill(activity_id: str, body: ReopenRequest, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db); require_csrf(request); activity = db.get(Activity, activity_id); require_member(db, activity, user); require_host(activity, user)
    if activity.billing_status not in ("issued", "settled"): raise HTTPException(409, detail={"code": "INVALID_TRANSITION", "message": "当前账单不能重新打开。"})
    pending = db.scalar(select(PaymentClaim.id).where(PaymentClaim.activity_id == activity_id, PaymentClaim.status == "claimed"))
    if pending: raise HTTPException(409, detail={"code": "PAYMENT_PENDING", "message": "请先确认或撤回待处理付款。"})
    activity.billing_status = "draft"; activity.bill_generation += 1; activity.version += 1; emit(db, "bill.reopened", activity=activity, actor=user, payload={"reason": body.reason}); db.commit()
    return activity_dto(db, activity, user)
