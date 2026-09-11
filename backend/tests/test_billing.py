import random

from shuttleup.billing.calculator import AllocatedExpense, ConfirmedPayment, ParticipantRef, allocate_equal, calculate_balances, simplify_transfers


def participants(n=4): return [ParticipantRef(chr(65+i), i+1, chr(65+i)) for i in range(n)]


def test_cent_remainders_never_go_negative():
    ps = participants(4)
    assert list(allocate_equal(2, ps).values()) == [1, 1, 0, 0]
    assert list(allocate_equal(1, ps[:3]).values()) == [1, 0, 0]
    assert list(allocate_equal(10_000, ps[:3]).values()) == [3334, 3333, 3333]


def test_golden_multi_payer_settlement():
    ps = participants()
    expenses = [
        AllocatedExpense("court", "A", 12000, allocate_equal(12000, ps)),
        AllocatedExpense("shuttle", "B", 4800, allocate_equal(4800, ps)),
        AllocatedExpense("parking", "C", 2000, allocate_equal(2000, [ps[0], ps[2]])),
    ]
    balances = calculate_balances(ps, expenses)
    assert balances == {"A": 6800, "B": 600, "C": -3200, "D": -4200}
    assert simplify_transfers(balances, ps) == [
        {"from_participant_id": "D", "to_participant_id": "A", "amount_cents": 4200},
        {"from_participant_id": "C", "to_participant_id": "A", "amount_cents": 2600},
        {"from_participant_id": "C", "to_participant_id": "B", "amount_cents": 600},
    ]


def test_1000_seeded_conservation_cases():
    rng = random.Random(20260918)
    for _ in range(1000):
        ps = participants(rng.randint(2, 12)); amount = rng.randint(1, 10_000_000); payer = ps[rng.randrange(len(ps))].id
        shares = allocate_equal(amount, ps)
        assert sum(shares.values()) == amount and min(shares.values()) >= 0 and max(shares.values()) - min(shares.values()) <= 1
        balances = calculate_balances(ps, [AllocatedExpense("e", payer, amount, shares)])
        transfers = simplify_transfers(balances, ps)
        confirmed = [ConfirmedPayment(str(i), t["from_participant_id"], t["to_participant_id"], t["amount_cents"]) for i,t in enumerate(transfers)]
        assert all(value == 0 for value in calculate_balances(ps, [AllocatedExpense("e", payer, amount, shares)], confirmed).values())
