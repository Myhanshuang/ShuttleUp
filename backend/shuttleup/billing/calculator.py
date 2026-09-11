from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParticipantRef:
    id: str
    join_order: int
    name: str = ""


@dataclass(frozen=True)
class AllocatedExpense:
    id: str
    payer_id: str
    amount_cents: int
    allocations: dict[str, int]


@dataclass(frozen=True)
class ConfirmedPayment:
    id: str
    from_id: str
    to_id: str
    amount_cents: int


def allocate_equal(amount_cents: int, participants: list[ParticipantRef]) -> dict[str, int]:
    if amount_cents < 0: raise ValueError("equal positive expense must not be negative")
    if not participants: raise ValueError("at least one participant is required")
    ordered = sorted(participants, key=lambda p: (p.join_order, p.id))
    quotient, remainder = divmod(amount_cents, len(ordered))
    return {p.id: quotient + (1 if index < remainder else 0) for index, p in enumerate(ordered)}


def allocate_exact(amount_cents: int, allocations: dict[str, int]) -> dict[str, int]:
    if len(allocations) != len(set(allocations)) or any(value < 0 for value in allocations.values()):
        raise ValueError("exact shares must be unique and non-negative")
    if sum(allocations.values()) != amount_cents: raise ValueError("exact shares must sum to expense")
    return dict(allocations)


def calculate_balances(participants: list[ParticipantRef], expenses: list[AllocatedExpense], payments: list[ConfirmedPayment] = ()) -> dict[str, int]:
    balances = {p.id: 0 for p in participants}
    for expense in expenses:
        if expense.payer_id not in balances: raise ValueError("payer does not belong to activity")
        if sum(expense.allocations.values()) != expense.amount_cents: raise ValueError("allocations do not conserve expense")
        balances[expense.payer_id] += expense.amount_cents
        for participant_id, amount in expense.allocations.items():
            if participant_id not in balances: raise ValueError("share does not belong to activity")
            balances[participant_id] -= amount
    for payment in payments:
        if payment.from_id not in balances or payment.to_id not in balances: raise ValueError("payment does not belong to activity")
        balances[payment.from_id] += payment.amount_cents
        balances[payment.to_id] -= payment.amount_cents
    if sum(balances.values()) != 0: raise AssertionError("balances must sum to zero")
    return balances


def simplify_transfers(balances: dict[str, int], participants: list[ParticipantRef]) -> list[dict]:
    order = {p.id: p.join_order for p in participants}
    creditors = sorted(((pid, value) for pid, value in balances.items() if value > 0), key=lambda item: (-item[1], order[item[0]], item[0]))
    debtors = sorted(((pid, -value) for pid, value in balances.items() if value < 0), key=lambda item: (-item[1], order[item[0]], item[0]))
    result = []; ci = di = 0
    while ci < len(creditors) and di < len(debtors):
        creditor_id, credit = creditors[ci]; debtor_id, debt = debtors[di]
        amount = min(credit, debt)
        result.append({"from_participant_id": debtor_id, "to_participant_id": creditor_id, "amount_cents": amount})
        credit -= amount; debt -= amount
        creditors[ci] = (creditor_id, credit); debtors[di] = (debtor_id, debt)
        if credit == 0: ci += 1
        if debt == 0: di += 1
    return result


def allocate_refund(amount_cents: int, original: dict[str, int], already_refunded: dict[str, int], join_order: dict[str, int]) -> dict[str, int]:
    if amount_cents >= 0: raise ValueError("refund must be negative")
    remaining = {pid: share - already_refunded.get(pid, 0) for pid, share in original.items()}
    refund = -amount_cents; total = sum(remaining.values())
    if refund > total: raise ValueError("refund exceeds original expense")
    raw = {pid: refund * value / total for pid, value in remaining.items() if value > 0}
    allocated = {pid: int(value) for pid, value in raw.items()}
    leftover = refund - sum(allocated.values())
    ranked = sorted(raw, key=lambda pid: (-(raw[pid] - allocated[pid]), join_order[pid], pid))
    for pid in ranked[:leftover]: allocated[pid] += 1
    return {pid: -value for pid, value in allocated.items()}

