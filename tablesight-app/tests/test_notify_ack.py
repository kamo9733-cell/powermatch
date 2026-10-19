from tablesight.notify.ack import AckTracker
from tablesight.notify.ack import DeliveryState as S


def tr():
    k = AckTracker()
    k.register("d1", "a1", "srv", 0)
    return k


def test_happy_path_and_history():
    k = tr()
    for st, t in [(S.DELIVERED, 1), (S.ACKED, 2), (S.RESOLVED, 3)]:
        assert k.apply("d1", st, t)
    assert [s for s, _ in k.get("d1").history] == [S.SENT, S.DELIVERED, S.ACKED, S.RESOLVED]


def test_idempotent_repeat_and_event_replay():
    k = tr()
    assert k.apply("d1", S.DELIVERED, 1, event_id="e1")
    assert not k.apply("d1", S.DELIVERED, 2)
    assert not k.apply("d1", S.ACKED, 3, event_id="e1")  # replayed event id ignored
    assert k.get("d1").state == S.DELIVERED


def test_out_of_order_receipt_does_not_regress():
    k = tr()
    assert k.apply("d1", S.ACKED, 1)  # ack arrives before delivery receipt
    assert not k.apply("d1", S.DELIVERED, 2)
    assert k.get("d1").state == S.ACKED


def test_terminal_states_are_final():
    k = tr()
    k.apply("d1", S.EXPIRED, 1)
    assert not k.apply("d1", S.ACKED, 2) and not k.apply("d1", S.RESOLVED, 3)
    k2 = tr()
    k2.apply("d1", S.RESOLVED, 1)
    assert not k2.apply("d1", S.EXPIRED, 2)


def test_register_idempotent_and_unknown_ignored():
    k = tr()
    k.apply("d1", S.DELIVERED, 1)
    assert k.register("d1", "a1", "srv", 99).state == S.DELIVERED
    assert not k.apply("nope", S.ACKED, 1)
    assert [r.delivery_id for r in k.for_alert("a1")] == ["d1"]
