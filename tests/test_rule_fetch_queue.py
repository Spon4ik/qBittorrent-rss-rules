from __future__ import annotations

import threading

from app.services import rule_fetch_queue


def test_rule_fetch_queue_joins_active_work_on_shutdown(monkeypatch) -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_fetch(*args, **kwargs):
        started.set()
        release.wait()
        finished.set()
        return {"status": "complete"}

    rule_fetch_queue.start_rule_fetch_queue()
    monkeypatch.setattr(rule_fetch_queue, "run_rules_fetch_batch", blocking_fetch)
    try:
        assert rule_fetch_queue.enqueue_rule_fetch("fixture-owned-rule") is True
        assert started.wait(timeout=1.0)
        release.set()
        rule_fetch_queue.stop_rule_fetch_queue()
    finally:
        release.set()
        rule_fetch_queue.stop_rule_fetch_queue()

    assert finished.is_set()
    assert rule_fetch_queue._WORKER is None
    assert not any(thread.name == "rule-fetch-queue" for thread in threading.enumerate())
