# SPDX-License-Identifier: MIT
# ============================================================
# Events service tests (task B-13, M3). Real Redis pub/sub -- a test
# subscriber on the same channel publish_ecosystem_changed() writes to.
# ============================================================

from __future__ import annotations

import json
import time

import pytest

from services.ecosystem import events_service


@pytest.fixture(autouse=True)
def _require_redis():
    try:
        events_service._get_redis().ping()
    except Exception as exc:
        pytest.skip(f"Redis not reachable: {exc}")


def _drain_one(pubsub, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = pubsub.get_message(timeout=0.2)
        if msg and msg.get("type") == "message":
            return json.loads(msg["data"])
    return None


def test_publish_delivers_to_a_real_subscriber():
    org_id = "org-events-1"
    r = events_service._get_redis()
    pubsub = r.pubsub()
    pubsub.subscribe(events_service._channel(org_id))
    try:
        # Give the subscription a moment to actually register before publishing --
        # PUBLISH to a channel with zero subscribers is a silent no-op, not an error.
        time.sleep(0.2)
        events_service.publish_ecosystem_changed(
            org_id, item_type="skill", item_id="item-1", scope="private",
            change="installed", version="1.0.0",
        )
        received = _drain_one(pubsub)
    finally:
        pubsub.close()

    assert received is not None
    assert received["v"] == 1
    assert received["type"] == "skill"
    assert received["item_id"] == "item-1"
    assert received["change"] == "installed"
    assert received["version"] == "1.0.0"


def test_publish_is_scoped_to_the_org_channel_only():
    r = events_service._get_redis()
    pubsub = r.pubsub()
    pubsub.subscribe(events_service._channel("org-events-other"))
    try:
        time.sleep(0.2)
        events_service.publish_ecosystem_changed(
            "org-events-2", item_type="skill", item_id="item-2", scope="private", change="installed",
        )
        received = _drain_one(pubsub, timeout=1.0)
    finally:
        pubsub.close()
    assert received is None, "a different org's channel must not receive this event"


def test_unknown_change_value_raises():
    with pytest.raises(ValueError, match="unknown change"):
        events_service.publish_ecosystem_changed(
            "org-events-3", item_type="skill", item_id="item-3", scope="private", change="not-a-real-change",
        )


def test_publish_never_raises_even_if_redis_is_unreachable(monkeypatch):
    def _broken_redis():
        raise ConnectionError("simulated redis outage")
    monkeypatch.setattr(events_service, "_get_redis", _broken_redis)

    # Must not raise -- a Redis outage must never turn a successful mutation
    # into a request-handler error.
    events_service.publish_ecosystem_changed(
        "org-events-4", item_type="skill", item_id="item-4", scope="private", change="installed",
    )
