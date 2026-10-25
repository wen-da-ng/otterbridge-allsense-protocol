"""A stand-in for the AllSense app's WebSocket server, so the client can be tested without a phone.

Implements the protocol v0 subset in spec/PROTOCOL.md: hello, catalog, subscribe/unsubscribe,
time_sync, status (refused, not_shared) and data (sine waves at the requested rate). See FakePhone
for how a test steers it (sharing, values, dropping the link).
"""

from __future__ import annotations

import copy
import json
import base64
import math
import struct
import threading
import time
from urllib.parse import parse_qs, urlparse

from websockets.sync.server import serve

TOKEN = "testtoken"
DEVICE = "rover"

STREAMS = [
    {"topic": f"allsense.{DEVICE}.sensors.accelerometer", "name": "accelerometer", "id": "sensors/1/acme/accel/n/0",
     "category": "sensors", "kind": "vector", "type": "Accelerometer", "sensor_type": 1, "hardware": "ACME Accel", "vendor": "ACME",
     "fields": ["x", "y", "z"], "unit": "m/s²", "reporting": "continuous", "max_rate_hz": 400.0, "wake_up": False, "basic": True},
    {"topic": f"allsense.{DEVICE}.sensors.light", "name": "light", "id": "sensors/5/acme/light/n/0",
     "category": "sensors", "kind": "vector", "type": "Light", "sensor_type": 5, "hardware": "ACME Light", "vendor": "ACME",
     "fields": ["illuminance"], "unit": "lx", "reporting": "on change", "max_rate_hz": None, "wake_up": False, "basic": True},
    {"topic": f"allsense.{DEVICE}.sensors.gyroscope", "name": "gyroscope", "id": "sensors/4/acme/gyro/n/0",
     "category": "sensors", "kind": "vector", "type": "Gyroscope", "sensor_type": 4, "hardware": "ACME Gyro", "vendor": "ACME",
     "fields": ["x", "y", "z"], "unit": "rad/s", "reporting": "continuous", "max_rate_hz": 400.0, "wake_up": False, "basic": True},
    {"topic": f"allsense.{DEVICE}.sensors.magnetic_field", "name": "magnetic_field", "id": "sensors/2/acme/mag/n/0",
     "category": "sensors", "kind": "vector", "type": "Magnetic field", "sensor_type": 2, "hardware": "ACME Mag", "vendor": "ACME",
     "fields": ["x", "y", "z"], "unit": "µT", "reporting": "continuous", "max_rate_hz": 100.0, "wake_up": False, "basic": True},
    {"topic": f"allsense.{DEVICE}.sensors.game_rotation_vector", "name": "game_rotation_vector", "id": "sensors/15/acme/grv/n/0",
     "category": "sensors", "kind": "vector", "type": "Game rotation vector", "sensor_type": 15, "hardware": "ACME GRV", "vendor": "ACME",
     "fields": ["x·sin(θ/2)", "y·sin(θ/2)", "z·sin(θ/2)", "cos(θ/2)"], "unit": "", "reporting": "continuous", "max_rate_hz": 200.0, "wake_up": False, "basic": True},
    {"topic": f"allsense.{DEVICE}.sensors.pressure", "name": "pressure", "id": "sensors/6/acme/baro/n/0",
     "category": "sensors", "kind": "vector", "type": "Pressure", "sensor_type": 6, "hardware": "ACME Baro", "vendor": "ACME",
     "fields": ["pressure"], "unit": "hPa", "reporting": "continuous", "max_rate_hz": 25.0, "wake_up": False, "basic": True},
    {"topic": f"allsense.{DEVICE}.sensors.proximity", "name": "proximity", "id": "sensors/8/acme/prox/n/0",
     "category": "sensors", "kind": "vector", "type": "Proximity", "sensor_type": 8, "hardware": "ACME Prox", "vendor": "ACME",
     "fields": ["distance"], "unit": "cm", "max_range": 5.0, "reporting": "on change", "max_rate_hz": None, "wake_up": True, "basic": True},
    {"topic": f"allsense.{DEVICE}.sensors.locked", "name": "locked", "id": "sensors/65000/acme/locked/n/0",
     "category": "sensors", "kind": "vector", "type": "com.acme.locked", "sensor_type": 65600, "hardware": "Locked", "vendor": "ACME",
     "fields": [], "unit": "", "reporting": "continuous", "max_rate_hz": 100.0, "wake_up": False, "basic": False},
    # The user hasn't shared this one over the network.
    {"topic": f"allsense.{DEVICE}.sensors.heart_rate", "name": "heart_rate", "id": "sensors/21/acme/hr/n/0",
     "category": "sensors", "kind": "vector", "type": "Heart rate", "sensor_type": 21, "hardware": "ACME HR", "vendor": "ACME",
     "fields": ["bpm"], "unit": "bpm", "reporting": "on change", "max_rate_hz": None, "wake_up": False, "basic": True, "shared": False},
    # Not Android sensors (spec/PROTOCOL.md, "Streams"): no sensor_type, per-field units.
    {"topic": f"allsense.{DEVICE}.gnss.position", "name": "position", "id": "gnss/position", "category": "gnss", "kind": "vector",
     "type": "GNSS position", "stream_type": "allsense.gnss.position", "sensor_type": None, "hardware": "ACME GNSS", "vendor": "Android",
     "fields": ["latitude", "longitude", "altitude", "accuracy", "speed", "bearing", "vertical accuracy"], "unit": "",
     "units": ["°", "°", "m", "m", "m/s", "°", "m"], "reporting": "on change", "max_rate_hz": 10.0, "wake_up": False, "basic": True},
    {"topic": f"allsense.{DEVICE}.camera.back", "name": "back", "id": "camera/0", "category": "camera", "kind": "image",
     "type": "Camera (back)", "stream_type": "allsense.camera.mjpeg", "sensor_type": None, "hardware": "Camera 0", "vendor": "Android",
     "fields": [], "unit": "", "units": [], "reporting": "continuous", "max_rate_hz": 30.0, "wake_up": False, "basic": True,
     "url": "/camera/back.mjpg", "facing": "back", "sensor_orientation": 90},
    {"topic": f"allsense.{DEVICE}.mic.mic", "name": "mic", "id": "mic/15/bottom/0", "category": "mic", "kind": "audio",
     "type": "Microphone", "stream_type": "allsense.mic.pcm16", "sensor_type": None, "hardware": "Built-in mic", "vendor": "Android",
     "fields": [], "unit": "", "units": [], "reporting": "continuous", "max_rate_hz": None, "wake_up": False, "basic": True,
     "url": "/mic/mic.wav", "sample_rates": [8000, 16000, 48000]},
    {"topic": f"allsense.{DEVICE}.battery.battery", "name": "battery", "id": "battery/main", "category": "battery", "kind": "vector",
     "type": "Battery", "stream_type": "allsense.battery", "sensor_type": None, "hardware": "Battery", "vendor": "Android",
     "fields": ["level", "voltage", "temperature", "current", "charging"], "unit": "", "units": ["%", "V", "°C", "mA", ""],
     "reporting": "continuous", "max_rate_hz": 10.0, "wake_up": False, "basic": True},
]

# Pretend the phone booted 1000 s before this computer's monotonic clock started: tests check the sync undoes it.
BOOT_OFFSET_NS = 1_000 * 1_000_000_000


def phone_now() -> int:
    return time.monotonic_ns() + BOOT_OFFSET_NS


def fake_values(name, t, seq):
    a = t / 1e9
    if name == "accelerometer":
        return [math.sin(a), math.cos(a), 9.81]
    if name == "gyroscope":
        return [0.1, -0.2, 0.3]
    if name == "magnetic_field":
        return [20.0, -5.0, -40.0]
    if name == "game_rotation_vector":  # 90° about z: (0, 0, sin 45°, cos 45°)
        return [0.0, 0.0, math.sqrt(0.5), math.sqrt(0.5)]
    if name == "pressure":
        return [1013.25]
    if name == "position":  # full double precision, like the phone's GNSS stream; no bearing (null)
        return [51.477928123456, -0.001545987654, 61.5, 4.0, 0.0, None, 6.0]
    if name == "battery":
        return [87.0, 4.012, 31.5, -412.0, 0.0]
    if name == "proximity":
        return [5.0 if seq % 2 else 0.0]
    if name == "attitude":  # roll, pitch, yaw, heading (°): facing north, slightly tilted
        return [2.0, -1.5, 90.0, 0.0]
    if name == "apriltag":  # tag 7, 1.2 m away, 10° to the left, drifting across the picture
        u = 0.5 + 0.2 * math.sin(a)
        return [7.0, u, 0.45, -0.21, -0.05, 1.18, 1.2, 10.0, 4.0, 85.0]
    return [float(seq)]


def robot_streams():
    """With the mount set in the app: motion sensors again in the robot's axes, plus attitude."""
    out = []
    for s in STREAMS:
        if s["name"] in ("accelerometer", "gyroscope", "game_rotation_vector"):
            r = copy.deepcopy(s)
            r.update(topic=f"allsense.{DEVICE}.robot.{s['name']}", id=f"robot/{s['name']}", category="robot", type=s["type"] + " (robot frame)")
            out.append(r)
    out.append({"topic": f"allsense.{DEVICE}.robot.attitude", "name": "attitude", "id": "robot/attitude", "category": "robot", "kind": "vector",
                "type": "Attitude (robot frame)", "stream_type": "allsense.robot.attitude", "sensor_type": None, "hardware": "ACME Fusion",
                "vendor": "ACME", "fields": ["roll", "pitch", "yaw", "heading"], "unit": "", "units": ["°"] * 4, "reporting": "continuous",
                "max_rate_hz": 200.0, "wake_up": False, "basic": True})
    return out


def vision_streams():
    """With Robot → AprilTags turned on: the vision.apriltag stream (spec/PROTOCOL.md, "Vision")."""
    return [{"topic": f"allsense.{DEVICE}.vision.apriltag", "name": "apriltag", "id": "vision/apriltag", "category": "vision",
             "kind": "vector", "type": "AprilTags", "stream_type": "allsense.vision.apriltag", "sensor_type": None,
             "hardware": "AprilRobotics tag36h11", "vendor": "AllSense",
             "fields": ["id", "u", "v", "x", "y", "z", "distance", "bearing", "yaw", "margin"], "unit": "",
             "units": ["", "", "", "m", "m", "m", "m", "°", "°", ""], "reporting": "continuous", "max_rate_hz": 30.0,
             "wake_up": False, "basic": True}]


class FakePhone:
    """A stand-in phone on a local port. Tests can also steer it like a user would:

    - ``set_shared(name, False)``: the user stops sharing a stream, ``True`` shares it again.
      Like the real phone, a subscription to an unshared stream is kept and starts once it's shared.
    - ``set_values(name, values)``: what a stream sends, a list or ``fn(t_seconds, seq) -> list``
      (e.g. to fake a bump). ``None`` goes back to the built-in values.
    - ``frozen.set()``: goes silent without closing anything, like Wi-Fi dropping. ``frozen.clear()`` resumes.
    - ``stop()`` then ``restart()``: the phone goes away and comes back on the same port.
    """

    def __init__(self, host="127.0.0.1", port=0, mounted=False, apriltags=False):
        self.connections = 0
        self.subscribe_messages = []
        # While set, the phone goes silent without closing anything, like Wi-Fi dropping.
        self.frozen = threading.Event()
        self.streams = copy.deepcopy(STREAMS) + (robot_streams() if mounted else []) + (vision_streams() if apriltags else [])
        self._values = {}
        # Like the app's Robot → Robot can control the phone switch (the real default is off).
        self.allow_commands = True
        self.commands_run = []
        self.volume = 0.6  # media volume, 0–1
        self.saved_sounds = {}  # name -> (format, bytes)
        self.camera_settings = {}
        self._clients = []
        self._clients_lock = threading.Lock()
        self._host = host
        self._serve(port)

    def _serve(self, port):
        self._server = serve(self._handler, self._host, port, process_request=self._http)
        self.port = self._server.socket.getsockname()[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={TOKEN}"

    def stop(self):
        self._server.shutdown()

    def restart(self):
        """Serves again on the same port after ``stop()``."""
        self._serve(self.port)

    def ping(self, timeout=2.0):
        """Like the app's link test: pings every client, returns their round trips in ms (None = no answer)."""
        with self._clients_lock:
            clients = list(self._clients)
        return [c.ping(timeout) for c in clients]

    def set_values(self, name, values):
        self._values[name] = values

    def set_shared(self, name, shared: bool):
        info = self._info(name)
        info["shared"] = shared
        with self._clients_lock:
            clients = list(self._clients)
        for c in clients:
            c.reshare(info)

    def _command(self, m):
        result = {"op": "command_result", "id": m.get("id"), "command": m.get("command")}
        if not self.allow_commands:
            return result | {"ok": False, "error": "Commands are off on the phone: Robot → Robot can control the phone"}
        name = m.get("command")
        if name not in ("ping", "vibrate", "torch", "tone", "say", "record", "display", "volume", "sound", "camera"):
            return result | {"ok": False, "error": f'Unknown command "{name}"'}
        # The phone's argument checks for the screen and sound commands (Commands.kt, DisplaySpec.kt).
        if name == "display" and m.get("action") != "clear":
            if m.get("face") is not None and m["face"] not in FACES:
                return result | {"ok": False, "error": f'Unknown face "{m["face"]}". Faces: {", ".join(FACES)}'}
            if not str(m.get("text", "")).strip() and m.get("face") is None:
                return result | {"ok": False, "error": '"display" needs "text" or "face" (or "action":"clear")'}
        if name == "sound":
            return result | self._sound(m)
        if name == "camera":
            return result | self._camera(m)
        self.commands_run.append(m)
        if name == "volume":
            if "level" in m:
                self.volume = min(1.0, max(0.0, float(m["level"])))
            return result | {"ok": True, "level": round(self.volume * 15) / 15}  # 15 steps, like a phone
        return result | {"ok": True}

    def _sound(self, m):
        """Saved sounds like the phone's SoundBox (names only; nothing plays)."""
        action, sound = m.get("action", "play"), m.get("name", "notification")
        builtin = ("notification", "alarm", "ringtone")
        if action == "list":
            return {"ok": True, "sounds": [{"name": n, "built_in": True} for n in builtin]
                    + [{"name": n, "format": f, "bytes": b} for n, (f, b) in sorted(self.saved_sounds.items())]}
        if action == "save":
            data = base64.b64decode(m.get("data", ""))
            if not data:
                return {"ok": False, "error": '"save" needs "data": the sound file in base64'}
            self.saved_sounds[sound] = (m.get("format") or "wav", len(data))
            return {"ok": True, "name": sound, "bytes": len(data)}
        if action == "delete":
            return {"ok": True} if self.saved_sounds.pop(sound, None) else {"ok": False, "error": f'No saved sound called "{sound}"'}
        if action == "play" and sound not in builtin and sound not in self.saved_sounds:
            return {"ok": False, "error": f'No sound called "{sound}". Sounds: {", ".join([*builtin, *self.saved_sounds])}'}
        self.commands_run.append(m)
        return {"ok": True}

    def _camera(self, m):
        """Camera settings like the phone's (a camera with full manual controls)."""
        if m.get("camera") not in ("back",):
            return {"ok": False, "error": f'No camera called "{m.get("camera")}". Cameras: back'}
        s = self.camera_settings
        if m.get("reset"):
            s.clear()
        if "white_balance" in m and m["white_balance"] not in ("auto", "daylight", "cloudy"):
            return {"ok": False, "error": '"white_balance" on this camera: auto, daylight, cloudy'}
        for k in ("ev", "iso", "exposure_ms", "focus", "white_balance", "ae_lock", "awb_lock"):
            if k in m:
                s[k] = m[k]
        self.commands_run.append(m)
        return {"ok": True, "camera": "back", "running": False,
                "settings": {"ev": s.get("ev"), "iso": s.get("iso"), "exposure_ms": s.get("exposure_ms"), "ae_lock": s.get("ae_lock", False),
                             "focus": s.get("focus", "auto"), "white_balance": s.get("white_balance", "auto"), "awb_lock": s.get("awb_lock", False)},
                "supports": {"ev_range": [-2.0, 2.0], "ev_step": 0.167, "iso_range": [50, 3200], "exposure_ms_range": [0.01, 500.0],
                             "min_focus_m": 0.1, "white_balances": ["auto", "daylight", "cloudy"], "ae_lock": True, "awb_lock": True}}

    def _info(self, name):
        return next(s for s in self.streams if name in (s["name"], s["topic"], s["id"]))

    def _value(self, name, t, seq):
        v = self._values.get(name)
        if v is None:
            return fake_values(name, t, seq)
        return list(v(t / 1e9, seq)) if callable(v) else list(v)

    def _http(self, connection, request):
        """Plain HTTP on the same port, like the phone: snapshots, short MJPEG and H.264 streams, a short WAV."""
        u = urlparse(request.path)
        if not u.path.startswith(("/camera/", "/mic/")):
            return None  # a WebSocket upgrade: carry on
        from websockets.datastructures import Headers
        from websockets.http11 import Response

        if parse_qs(u.query).get("token", [None])[0] != TOKEN:
            return Response(401, "Unauthorized", Headers([("Content-Length", "0")]), b"")
        if u.path == "/mic/mic.wav":
            return Response(200, "OK", Headers([("Content-Type", "audio/wav"), ("Content-Length", str(len(FAKE_WAV))),
                                                ("X-Timestamp-Ns", "5000000000"), ("X-Sample-Rate", "16000")]), FAKE_WAV)
        if u.path in ("/camera/back.mjpg", "/camera/back.h264"):
            body = FAKE_H264_PARTS if u.path.endswith(".h264") else FAKE_MJPEG_PARTS
            return Response(200, "OK", Headers([("Content-Type", "multipart/x-mixed-replace; boundary=allsenseframe"),
                                                ("Content-Length", str(len(body)))]), body)
        if u.path != "/camera/back.jpg":
            body = b"No camera called that"
            return Response(404, "Not Found", Headers([("Content-Length", str(len(body)))]), body)
        return Response(200, "OK", Headers([("Content-Type", "image/jpeg"), ("Content-Length", str(len(FAKE_JPEG)))]), FAKE_JPEG)

    def _handler(self, ws):
        q = parse_qs(urlparse(ws.request.path).query)
        if q.get("token", [None])[0] != TOKEN:
            ws.close(1008, "Wrong or missing token")
            return
        self.connections += 1
        client = _Client(self, ws, wants_catalog=q.get("catalog", [None])[0] != "none")
        with self._clients_lock:
            self._clients.append(client)
        try:
            client.run()
        finally:
            with self._clients_lock:
                self._clients.remove(client)


NOT_SHARED = "Not shared over Network (app: Home → Connect → Browser → Streams it may send)"
FACES = ("happy", "sad", "neutral", "surprised", "thinking", "sleepy", "angry")
# Enough of a JPEG for tests: start and end markers around some bytes.
FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg" * 10 + b"\xff\xd9"
# 0.25 s of a 1 kHz tone at 16 kHz, as the phone sends it (endless-WAV header, then 16-bit samples).
FAKE_WAV = (b"RIFF\xff\xff\xff\xffWAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16) + b"data\xff\xff\xff\xff"
            + b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 1000 * i / 16000))) for i in range(4000)))


def _parts(frames, content_type):
    """A short (finite) camera stream: multipart parts as the phone sends them, 10 frames apart by 0.1 s."""
    out = b""
    for i, (data, key) in enumerate(frames):
        out += (b"--allsenseframe\r\nContent-Type: %s\r\nContent-Length: %d\r\nX-Timestamp-Ns: %d\r\nX-Size: 640x480\r\n"
                % (content_type, len(data), 5_000_000_000 + i * 100_000_000))
        out += (b"X-Keyframe: %d\r\n" % key if key is not None else b"") + b"\r\n" + data + b"\r\n"
    return out


FAKE_MJPEG_PARTS = _parts([(FAKE_JPEG, None)] * 10, b"image/jpeg")
# Starts mid-GOP like a late joiner: one delta frame, then a keyframe (SPS, PPS, IDR) and more deltas.
_SPS_PPS_IDR = b"\x00\x00\x00\x01\x67fake-sps\x00\x00\x00\x01\x68fake-pps\x00\x00\x00\x01\x65fake-idr"
FAKE_H264_PARTS = _parts([(b"\x00\x00\x00\x01\x41fake-p", 0), (_SPS_PPS_IDR, 1)] + [(b"\x00\x00\x00\x01\x41fake-p", 0)] * 8,
                         b"video/h264")


class _Client:
    """One connected client, with the phone's subscription rules."""

    def __init__(self, phone, ws, wants_catalog):
        self.phone, self.ws, self.wants_catalog = phone, ws, wants_catalog
        self.lock = threading.Lock()
        self.wanted = {}  # topic -> rate, including subscriptions waiting to be shared
        self.flags = {}  # topic -> stop flag of its running pump
        self.pongs = {}  # ping id -> Event

    def send(self, m):
        if self.phone.frozen.is_set():
            return
        with self.lock:
            self.ws.send(json.dumps(m))

    def catalog(self):
        self.send({"op": "catalog", "device": DEVICE, "streams": self.phone.streams})

    def start(self, info):
        topic = info["topic"]
        self.stop(topic)
        if info["name"] == "locked":
            self.send({"op": "status", "topic": topic, "state": "refused", "reason": "Android won't deliver this sensor to apps"})
            return
        if not info.get("shared", True):
            self.send({"op": "status", "topic": topic, "state": "not_shared", "reason": NOT_SHARED})
            return
        rate = self.wanted[topic] if info["reporting"] == "continuous" else 20
        flag = self.flags[topic] = threading.Event()
        threading.Thread(target=self.pump, args=(info["name"], topic, rate, flag), daemon=True).start()
        self.send({"op": "subscribed", "topic": topic, "rate_hz": rate if info["reporting"] == "continuous" else None})

    def ping(self, timeout):
        pid = len(self.pongs) + 1
        done = self.pongs[pid] = threading.Event()
        start = time.perf_counter()
        self.send({"op": "ping", "id": pid})
        self.send({"op": "fill", "pad": "x" * 100})  # clients must ignore it
        return (time.perf_counter() - start) * 1000 if done.wait(timeout) else None

    def stop(self, topic):
        flag = self.flags.pop(topic, None)
        if flag:
            flag.set()

    def reshare(self, info):
        if self.wants_catalog:
            self.catalog()
        if info["topic"] in self.wanted:
            self.start(info)  # starts it, or sends not_shared and stops it

    def pump(self, name, topic, rate, flag):
        seq = 0
        due = time.monotonic()
        while not flag.is_set():
            t = phone_now()
            try:
                self.send({"op": "data", "topic": topic, "seq": seq, "t": t, "v": self.phone._value(name, t, seq), "acc": 3})
            except Exception:
                return
            seq += 1
            # Each sample is due at a fixed time, so the average rate holds even when the OS sleeps longer than
            # asked (busy CI machines). Far behind (e.g. after a pause): start afresh instead of a burst.
            due += 1.0 / rate
            now = time.monotonic()
            if now - due > 0.5:
                due = now
            flag.wait(max(0.0, due - now))

    def run(self):
        self.send({"op": "hello", "protocol": 0, "app": "AllSense", "app_version": "test", "device": DEVICE,
                   "clock": "boottime_ns", "boot_to_unix_ns": time.time_ns() - phone_now()})
        if self.wants_catalog:
            self.catalog()
        try:
            for raw in self.ws:
                m = json.loads(raw)
                op = m.get("op")
                if op == "subscribe":
                    self.phone.subscribe_messages.append(m)
                    for topic in m.get("topics", []):
                        info = next((s for s in self.phone.streams if s["topic"] == topic), None)
                        if info is None:
                            self.send({"op": "error", "message": f'Unknown topic "{topic}"'})
                            continue
                        self.wanted[topic] = m.get("rate_hz", 50)
                        self.start(info)
                elif op == "unsubscribe":
                    topics = list(self.wanted) if m.get("all") else m.get("topics", [])
                    for topic in topics:
                        self.wanted.pop(topic, None)
                        self.stop(topic)
                elif op == "time_sync":
                    t1 = phone_now()
                    self.send({"op": "time_sync", "t0": m.get("t0"), "t1": t1, "t2": phone_now()})
                elif op == "catalog":
                    self.catalog()
                elif op == "command":
                    self.send(self.phone._command(m))
                elif op == "pong" and m.get("id") in self.pongs:
                    self.pongs[m["id"]].set()
        finally:
            for flag in self.flags.values():
                flag.set()


def main():
    """allsense-fake-phone: a stand-in phone on this computer, e.g. for testing the ROS 2 bridge."""
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--mounted", action="store_true", help="the phone's mount is set: robot-frame streams too")
    ap.add_argument("--apriltags", action="store_true", help="AprilTag detection is on: the vision.apriltag stream too")
    a = ap.parse_args()
    phone = FakePhone(a.host, a.port, mounted=a.mounted, apriltags=a.apriltags)
    print(f"Fake AllSense phone: http://{a.host}:{phone.port}/?token={TOKEN}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        phone.stop()


if __name__ == "__main__":
    main()
