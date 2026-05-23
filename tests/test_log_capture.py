from sitop_loxone_bridge.log_capture import LogBuffer, capture_processor


def test_buffer_caps_at_capacity() -> None:
    buf = LogBuffer(capacity=3)
    for i in range(5):
        buf.append({"i": i})
    assert [e["i"] for e in buf.snapshot()] == [2, 3, 4]


def test_snapshot_limit() -> None:
    buf = LogBuffer(capacity=10)
    for i in range(6):
        buf.append({"i": i})
    assert [e["i"] for e in buf.snapshot(limit=2)] == [4, 5]
    assert len(buf.snapshot(limit=20)) == 6


def test_capture_processor_appends_to_module_buffer() -> None:
    from sitop_loxone_bridge.log_capture import LOG_BUFFER

    LOG_BUFFER.clear()
    event = {"event": "test", "level": "info", "timestamp": "2026-01-01", "k": 1}
    capture_processor(logger=None, method_name="info", event_dict=event)
    snap = LOG_BUFFER.snapshot()
    assert snap[-1] == event


def test_capture_processor_returns_event_unchanged() -> None:
    event = {"event": "x", "level": "warning"}
    result = capture_processor(logger=None, method_name="warning", event_dict=event)
    assert result is event


def test_successful_tick_is_not_captured() -> None:
    from sitop_loxone_bridge.log_capture import LOG_BUFFER

    LOG_BUFFER.clear()
    capture_processor(
        logger=None,
        method_name="info",
        event_dict={
            "event": "tick",
            "level": "info",
            "parameters": 3,
            "http_ok": 3,
            "http_fail": 0,
        },
    )
    assert LOG_BUFFER.snapshot() == []


def test_failed_tick_is_captured() -> None:
    from sitop_loxone_bridge.log_capture import LOG_BUFFER

    LOG_BUFFER.clear()
    capture_processor(
        logger=None,
        method_name="info",
        event_dict={
            "event": "tick",
            "level": "info",
            "parameters": 3,
            "http_ok": 1,
            "http_fail": 2,
        },
    )
    assert len(LOG_BUFFER.snapshot()) == 1
