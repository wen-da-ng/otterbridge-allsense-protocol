"""Frame templates (spec/TEMPLATES.md) on the PC: encode, decode and check frames.

Written separately from the app's Kotlin encoder on purpose: both must produce the bytes in
vectors/template_vectors.json, so a mistake in one shows up as a test failure.

    allsense-template check  templates/my_robot_imu.json [more.json]   settings + byte map of an example frame
    allsense-template decode templates/my_robot_imu.json "AA 55 d5 03 ..."
"""

from __future__ import annotations

import json
import math
import struct
import sys

TYPES = {"u8": ("B", 0, 255), "i8": ("b", -128, 127), "u16": ("H", 0, 65535), "i16": ("h", -32768, 32767),
         "u32": ("I", 0, 4294967295), "i32": ("i", -2147483648, 2147483647), "f32": ("f", None, None)}
CHECKSUMS = {"none": 0, "xor8": 1, "sum8": 1, "crc8": 1, "crc16_ccitt": 2}


def _hex(text: str) -> bytes:
    return bytes.fromhex(text.lower().replace("0x", "").replace(",", " "))


class Template:
    def __init__(self, d: dict):
        self.raw = dict(d)
        if "ble" in d:  # 16-bit UUIDs like "FFE1" expand with the Bluetooth base UUID, as in the app
            self.raw["ble"] = {k: (f"0000{v.lower()}-0000-1000-8000-00805f9b34fb" if len(v) == 4 else v.lower())
                               for k, v in d["ble"].items()}
        self.name = d["name"]
        self.rate_hz = float(d["rate_hz"])
        self.header = _hex(d.get("header", ""))
        self.endian = "<" if d.get("endian", "little") == "little" else ">"
        self.checksum = d.get("checksum", "none")
        if self.checksum not in CHECKSUMS:
            raise ValueError(f"unknown checksum {self.checksum}")
        self.covers_all = d.get("checksum_covers", "after_header") == "all"
        self.baud = int(d.get("baud", 115200))
        self.fields = []
        for f in d["fields"]:
            t = f["type"]
            if t.startswith("seq_"):
                self.fields.append(("seq", t[4:]))
            elif t == "const":
                self.fields.append(("const", _hex(f["bytes"])))
            else:
                idx = f.get("idx", [0])
                idx = [idx] if isinstance(idx, int) else idx
                self.fields.append(("value", f["src"], idx, t, float(f.get("scale", 1)), float(f.get("offset", 0))))

    @classmethod
    def load(cls, path: str) -> "Template":
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))

    @property
    def sources(self):
        return list(dict.fromkeys(f[1] for f in self.fields if f[0] == "value"))

    @property
    def size(self) -> int:
        n = len(self.header) + CHECKSUMS[self.checksum]
        for f in self.fields:
            if f[0] == "seq":
                n += struct.calcsize(TYPES[f[1]][0])
            elif f[0] == "const":
                n += len(f[1])
            else:
                n += len(f[2]) * struct.calcsize(TYPES[f[3]][0])
        return n

    def _put(self, t: str, v: float) -> bytes:
        fmt, lo, hi = TYPES[t]
        if t == "f32":
            return struct.pack(self.endian + fmt, v)
        r = math.floor(min(max(v, lo), hi) + 0.5)  # round half up, like Kotlin's roundToLong
        return struct.pack(self.endian + fmt, int(min(max(r, lo), hi)))

    def encode(self, values: dict, seq: int) -> bytes:
        out = bytearray(self.header)
        for f in self.fields:
            if f[0] == "seq":
                fmt = TYPES[f[1]][0]
                out += struct.pack(self.endian + fmt, seq % (1 << (8 * struct.calcsize(fmt))))
            elif f[0] == "const":
                out += f[1]
            else:
                _, src, idx, t, scale, offset = f
                v = values[src]
                for i in idx:
                    x = v[i] if i < len(v) and v[i] is not None and math.isfinite(v[i]) else 0.0
                    out += self._put(t, x * scale + offset)
        out += self._checksum(bytes(out))
        return bytes(out)

    def _checksum(self, frame: bytes) -> bytes:
        body = frame if self.covers_all else frame[len(self.header):]
        if self.checksum == "xor8":
            c = 0
            for b in body:
                c ^= b
            return bytes([c])
        if self.checksum == "sum8":
            return bytes([sum(body) & 0xFF])
        if self.checksum == "crc8":
            c = 0
            for b in body:
                c ^= b
                for _ in range(8):
                    c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
            return bytes([c])
        if self.checksum == "crc16_ccitt":
            c = 0xFFFF
            for b in body:
                c ^= b << 8
                for _ in range(8):
                    c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
            return struct.pack(self.endian + "H", c)
        return b""

    def decode(self, frame: bytes) -> dict:
        """Values per source (scale and offset undone) plus 'seq'. Raises ValueError on a bad frame."""
        if len(frame) != self.size:
            raise ValueError(f"frame is {len(frame)} bytes, template says {self.size}")
        if not frame.startswith(self.header):
            raise ValueError("header doesn't match")
        n = CHECKSUMS[self.checksum]
        if n and self._checksum(frame[:-n]) != frame[-n:]:
            raise ValueError("checksum doesn't match")
        at, out = len(self.header), {}
        for f in self.fields:
            if f[0] == "seq":
                fmt = self.endian + TYPES[f[1]][0]
                out["seq"] = struct.unpack_from(fmt, frame, at)[0]
                at += struct.calcsize(fmt)
            elif f[0] == "const":
                if frame[at:at + len(f[1])] != f[1]:
                    raise ValueError("constant bytes don't match")
                at += len(f[1])
            else:
                _, src, idx, t, scale, offset = f
                fmt = self.endian + TYPES[t][0]
                vals = out.setdefault(src, {})
                for i in idx:
                    vals[i] = (struct.unpack_from(fmt, frame, at)[0] - offset) / scale
                    at += struct.calcsize(fmt)
        return out


def check(t: Template, file: str) -> None:
    """Prints the settings and a byte map of one example frame, to compare with the board's protocol."""
    rate = t.size * t.rate_hz
    print(f'OK   {file}: "{t.name}", {t.size}-byte frames at {t.rate_hz:g} Hz = {rate:.0f} B/s')
    covers = "the whole frame" if t.covers_all else "the bytes after the header"
    print(f"     {'little' if t.endian == '<' else 'big'}-endian, checksum {t.checksum}"
          + (f" over {covers}" if t.checksum != "none" else "") + f", {t.baud} baud")
    print(f"     streams: {', '.join(t.sources)} (names as set in the app; see spec/TEMPLATES.md)")
    if t.raw.get("description", "").startswith("Replace with"):
        print('     warning: "description" is still the starter\'s text')
    if rate > t.baud / 10 * 0.8:
        print(f"     warning: that's more than {t.baud} baud carries comfortably (~{t.baud // 10} B/s). Lower rate_hz or raise baud.")

    # Example: value i of every stream is i + 1 (so x = 1, y = 2, z = 3), counter 0.
    frame = t.encode({s: [i + 1.0 for i in range(64)] for s in t.sources}, 0)
    print("     example frame, with value i of each stream = i + 1 and counter 0:")
    print("       " + frame.hex(" ").upper())
    at = 0

    def row(n: int, what: str) -> None:
        nonlocal at
        span = f"{at}" if n == 1 else f"{at}-{at + n - 1}"
        print(f"       bytes {span:<7} {frame[at:at + n].hex(' ').upper():<12} {what}")
        at += n

    if t.header:
        row(len(t.header), "header")
    for f in t.fields:
        if f[0] == "seq":
            row(struct.calcsize(TYPES[f[1]][0]), f"counter ({f[1]})")
        elif f[0] == "const":
            row(len(f[1]), "constant")
        else:
            _, src, idx, typ, scale, offset = f
            for i in idx:
                row(struct.calcsize(TYPES[typ][0]), f"{src}[{i}] = {i + 1}" + (f" x {scale:g}" if scale != 1 else "")
                    + (f" + {offset:g}" if offset else "") + f" as {typ}")
    if CHECKSUMS[t.checksum]:
        row(CHECKSUMS[t.checksum], f"checksum ({t.checksum})")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2 or argv[0] not in ("check", "decode"):
        print(__doc__)
        return 2
    if argv[0] == "check":
        failed = False
        for path in argv[1:]:
            try:
                check(Template.load(path), path.replace("\\", "/").rsplit("/", 1)[-1])
            except (OSError, ValueError, KeyError, TypeError) as e:
                failed = True
                print(f'FAIL {path}: missing "{e.args[0]}"' if isinstance(e, KeyError) else f"FAIL {path}: {e}")
        return 1 if failed else 0
    print(Template.load(argv[1]).decode(_hex(" ".join(argv[2:]))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
