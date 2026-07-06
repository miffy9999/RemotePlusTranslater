from translator_app.events import EventBus


def test_slow_subscriber_is_bounded_and_gets_latest_event():
    bus = EventBus(subscriber_size=2)
    queue = bus.subscribe()
    for number in range(5):
        bus.publish("status", number=number)
    assert queue.qsize() == 2
    assert queue.get_nowait().data["number"] == 3
    assert queue.get_nowait().data["number"] == 4


def test_only_useful_events_are_replayed():
    bus = EventBus()
    bus.publish("status", message="busy")
    bus.publish("translation", translated="日本語")
    assert len(bus.history()) == 1


def test_history_can_be_cleared():
    bus = EventBus()
    bus.publish("translation", translated="private")
    bus.clear_history()
    assert bus.history() == []
