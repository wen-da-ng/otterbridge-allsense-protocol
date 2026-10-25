"""AllSense compact protocol (spec/PROTOCOL.md, "Compact protocol") in plain Python.

Used by the PC test tools in this folder to play the phone towards a board over USB serial or
BLE. Independent from the app's and the Arduino library's versions; all must agree byte for byte with
vectors/compact_vectors.json. `python -m allsense_testkit.compact` runs the vectors below.

MIT licensed.
"""

import struct

HELLO, SUBSCRIBE, UNSUBSCRIBE, STATUS, HEARTBEAT, PING, PONG, FILL, DATA = 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x10
STATUS_OK, STATUS_UNKNOWN_NAME, STATUS_REFUSED, STATUS_ARMED, STATUS_NOT_SHARED = 0, 1, 2, 3, 4
STATUS_NAMES = {STATUS_OK: "ok", STATUS_UNKNOWN_NAME: "unknown-name", STATUS_REFUSED: "refused", STATUS_ARMED: "armed",
                STATUS_NOT_SHARED: "not-shared"}
NAMES = {HELLO: "HELLO", SUBSCRIBE: "SUBSCRIBE", UNSUBSCRIBE: "UNSUBSCRIBE", STATUS: "STATUS", HEARTBEAT: "HEARTBEAT",
         PING: "PING", PONG: "PONG", FILL: "FILL", DATA: "DATA"}

BLE_SERVICE = "a1150001-ae7a-4681-958d-74782a0d0f32"
BLE_RX = "a1150002-ae7a-4681-958d-74782a0d0f32"  # phone -> board (write without response)
BLE_TX = "a1150003-ae7a-4681-958d-74782a0d0f32"  # board -> phone (notify)


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def cobs_encode(data: bytes) -> bytes:
    """Canonical COBS (no empty block after a run ending exactly on 254 bytes)."""
    out, block, full = bytearray(), bytearray(), False
    for b in data:
        full = False
        if b == 0:
            out.append(len(block) + 1); out += block; block = bytearray()
        else:
            block.append(b)
            if len(block) == 254:
                out.append(255); out += block; block = bytearray(); full = True
    if not full:
        out.append(len(block) + 1); out += block
    return bytes(out)


def cobs_decode(data: bytes):
    out, i = bytearray(), 0
    while i < len(data):
        code = data[i]
        if code == 0 or i + code > len(data):
            return None
        out += data[i + 1:i + code]
        i += code
        if code < 255 and i < len(data):
            out.append(0)
    return bytes(out)


def frame(payload: bytes) -> bytes:
    """Payload -> bytes on the wire: COBS(payload + CRC16 LE) + 0x00."""
    crc = crc16(payload)
    return cobs_encode(payload + bytes([crc & 0xFF, crc >> 8])) + b"\x00"


class Reader:
    """Feed it received bytes; returns complete, valid payloads (corrupt frames are dropped)."""

    def __init__(self):
        self.buffer = b""
        self.corrupt = 0

    def feed(self, data: bytes):
        self.buffer += data
        *parts, self.buffer = self.buffer.split(b"\x00")
        payloads = []
        for part in parts:
            if not part:
                continue
            raw = cobs_decode(part)
            if raw and len(raw) >= 3 and crc16(raw[:-2]) == raw[-2] | (raw[-1] << 8):
                payloads.append(raw[:-2])
            else:
                self.corrupt += 1
        return payloads


def hello(name: str) -> bytes:
    return bytes([HELLO, 0]) + name.encode()[:64]


def status(stream_id: int, code: int = 0, text: str = "") -> bytes:
    return bytes([STATUS, stream_id, code]) + text.encode()[:80]


def data(stream_id: int, seq: int, t_us: int, accuracy: int, values) -> bytes:
    return struct.pack("<BBHIbB", DATA, stream_id, seq & 0xFFFF, t_us & 0xFFFFFFFF, accuracy, len(values)) + \
        struct.pack(f"<{len(values)}f", *values)


def subscribe(stream_id: int, rate_hz: float, name: str) -> bytes:
    return struct.pack("<BBf", SUBSCRIBE, stream_id, rate_hz) + name.encode()


def ping(token: int) -> bytes:
    return struct.pack("<Bi", PING, token)


def describe(payload: bytes) -> str:
    """Human-readable summary of a payload, for logs."""
    kind = payload[0]
    if kind == HELLO:
        return f"HELLO name={payload[2:].decode(errors='replace')!r}"
    if kind == SUBSCRIBE:
        rate = struct.unpack("<f", payload[2:6])[0]
        return f"SUBSCRIBE id={payload[1]} rate={rate:g} Hz name={payload[6:].decode(errors='replace')!r}"
    if kind == UNSUBSCRIBE:
        return f"UNSUBSCRIBE id={payload[1]}"
    if kind == STATUS:
        code = STATUS_NAMES.get(payload[2], str(payload[2]))
        return f"STATUS id={payload[1]} {code} {payload[3:].decode(errors='replace')}"
    if kind in (PING, PONG) and len(payload) >= 5:
        return f"{NAMES[kind]} token={struct.unpack('<i', payload[1:5])[0]}"
    if kind == DATA:
        n = payload[9]
        values = struct.unpack(f"<{n}f", payload[10:10 + 4 * n])
        return f"DATA id={payload[1]} seq={struct.unpack('<H', payload[2:4])[0]} values={tuple(round(v, 3) for v in values)}"
    return NAMES.get(kind, f"type 0x{kind:02x}")


if __name__ == "__main__":
    # Shared vectors (as in vectors/compact_vectors.json and spec/PROTOCOL.md).
    assert crc16(b"123456789") == 0x29B1
    for raw, enc in [("00", "0101"), ("0000", "010101"), ("001100", "01021101"), ("11220033", "0311220233"),
                     ("11223344", "0511223344"), ("11000000", "0211010101"), ("", "01")]:
        assert cobs_encode(bytes.fromhex(raw)).hex() == enc, raw
        assert cobs_decode(bytes.fromhex(enc)).hex() == raw, enc
    run = bytes(range(1, 255))
    assert cobs_encode(run) == b"\xff" + run
    assert frame(subscribe(1, 50.0, "accelerometer")).hex() == "03020101124842616363656c65726f6d65746572b12100"
    assert frame(data(3, 513, 123456789, 3, (0.0, 1.5, -9.81))).hex() == "0b1003010215cd5b070303010101010109c03fc3f51cc18f6f00"
    assert ping(0x01020304).hex() == "0604030201"
    r = Reader()
    assert r.feed(b"\x41\x42\x00" + frame(hello("x"))) == [hello("x")] and r.corrupt == 1
    print("allsense_compact: all vectors OK")
