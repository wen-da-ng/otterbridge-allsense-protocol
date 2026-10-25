"""The WebSocket fake phone speaks spec/PROTOCOL.md, checked with a raw WebSocket client."""

import json
import time
import urllib.error
import urllib.request

import pytest
from websockets.sync.client import connect

from allsense_testkit import DEVICE, TOKEN, FakePhone


@pytest.fixture
def phone():
    p = FakePhone()
    yield p
    p.stop()


def ws_url(phone, token=TOKEN, extra=""):
    return f"ws://127.0.0.1:{phone.port}/ws?token={token}{extra}"


def until(ws, op, timeout=5.0, **match):
    """The next message with this op (and matching fields)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        m = json.loads(ws.recv(timeout=max(0.05, end - time.monotonic())))
        if m.get("op") == op and all(m.get(k) == v for k, v in match.items()):
            return m
    raise AssertionError(f"no {op} {match} within {timeout} s")


def test_hello_then_catalog(phone):
    with connect(ws_url(phone)) as ws:
        hello = json.loads(ws.recv(timeout=5))
        assert hello["op"] == "hello" and hello["protocol"] == 0 and hello["device"] == DEVICE
        assert isinstance(hello["boot_to_unix_ns"], int)
        catalog = until(ws, "catalog")
        names = {s["name"] for s in catalog["streams"]}
        assert {"accelerometer", "position", "back", "mic"} <= names


def test_no_catalog_for_small_devices(phone):
    with connect(ws_url(phone, extra="&catalog=none")) as ws:
        assert json.loads(ws.recv(timeout=5))["op"] == "hello"
        ws.send(json.dumps({"op": "subscribe", "topics": [f"allsense.{DEVICE}.sensors.accelerometer"], "rate_hz": 50}))
        assert until(ws, "subscribed")  # no catalog came first


def test_wrong_token_is_refused(phone):
    with connect(ws_url(phone, token="nope")) as ws:
        with pytest.raises(Exception) as e:
            ws.recv(timeout=5)
    assert "1008" in str(e.value)


def test_samples_and_rate(phone):
    topic = f"allsense.{DEVICE}.sensors.accelerometer"
    with connect(ws_url(phone)) as ws:
        ws.send(json.dumps({"op": "subscribe", "topics": [topic], "rate_hz": 50}))
        assert until(ws, "subscribed", topic=topic)["rate_hz"] == 50
        a = until(ws, "data", topic=topic)
        b = until(ws, "data", topic=topic)
        assert a["v"][2] == 9.81 and b["seq"] == a["seq"] + 1 and b["t"] > a["t"]


def test_refused_and_not_shared(phone):
    with connect(ws_url(phone)) as ws:
        ws.send(json.dumps({"op": "subscribe", "topics": [f"allsense.{DEVICE}.sensors.locked", f"allsense.{DEVICE}.sensors.heart_rate"]}))
        assert until(ws, "status", state="refused")["reason"]
        assert until(ws, "status", state="not_shared")
        phone.set_shared("heart_rate", True)
        assert until(ws, "subscribed", topic=f"allsense.{DEVICE}.sensors.heart_rate")


def test_time_sync_and_commands(phone):
    with connect(ws_url(phone)) as ws:
        ws.send(json.dumps({"op": "time_sync", "t0": 123}))
        r = until(ws, "time_sync")
        assert r["t0"] == 123 and r["t2"] >= r["t1"]
        ws.send(json.dumps({"op": "command", "id": 1, "command": "vibrate", "ms": 50}))
        assert until(ws, "command_result", id=1)["ok"] is True
        ws.send(json.dumps({"op": "command", "id": 2, "command": "fly"}))
        assert until(ws, "command_result", id=2)["ok"] is False


def test_snapshot_over_http(phone):
    with urllib.request.urlopen(f"http://127.0.0.1:{phone.port}/camera/back.jpg?token={TOKEN}", timeout=5) as r:
        assert r.read()[:2] == b"\xff\xd8"
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(f"http://127.0.0.1:{phone.port}/camera/back.jpg?token=nope", timeout=5)
    assert e.value.code == 401


def test_optional_streams():
    p = FakePhone(mounted=True, apriltags=True)
    try:
        with connect(ws_url(p)) as ws:
            ids = {s["id"] for s in until(ws, "catalog")["streams"]}
        assert {"robot/attitude", "vision/apriltag"} <= ids
    finally:
        p.stop()
