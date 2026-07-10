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


def test_history_never_grows_beyond_configured_limit():
    bus = EventBus(history_size=3)
    for number in range(10):
        bus.publish("translation", number=number)
    assert [item["data"]["number"] for item in bus.history()] == [7, 8, 9]
