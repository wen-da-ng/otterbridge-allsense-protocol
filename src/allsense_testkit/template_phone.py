"""Play the phone towards a board that reads frame templates (spec/TEMPLATES.md), over USB serial or BLE.

Sends template frames with known values and checks what the board reports back. Works with the
TemplateReader / TemplateReaderBLE examples, which report "frames=… bad=… accel_x100=…" once a second:

    allsense-fake-template --port COM3 --template templates/my_robot_imu.json
    allsense-fake-template --ble "Robot NUS" --template templates/my_robot_imu.json

Over BLE the frames go to the Nordic UART or HM-10 (FFE0/FFE1) write characteristic, or the one
the template names, and reports are read from notifications. The board must not be connected to
the phone. Windows timers cap BLE writes near 30-60 per second, so fewer frames go out than the
template's rate; that's fine for checking.

A board that can't report (e.g. firmware you can't change): frames are still sent and anything it
says is shown, then the tool says the frames weren't verified. Check the board's own behaviour
instead. Close the Arduino Serial Monitor first.
"""

import argparse
import math
import os
import re
import sys
import time

from .template import Template

# (service, write characteristic, notify characteristic) of common BLE serial services.
UART_SERVICES = [
    ("6e400001-b5a3-f393-e0a9-e50e24dcca9e", "6e400002-b5a3-f393-e0a9-e50e24dcca9e", "6e400003-b5a3-f393-e0a9-e50e24dcca9e"),
    ("0000ffe0-0000-1000-8000-00805f9b34fb", "0000ffe1-0000-1000-8000-00805f9b34fb", "0000ffe1-0000-1000-8000-00805f9b34fb"),
]

# Plausible resting values for common streams (phone lying flat), so range checks on a real
# controller don't trip. Anything else gets small values around 1.
TYPICAL = {
    "accelerometer": [0.0, 0.0, 9.81], "gravity": [0.0, 0.0, 9.81], "linear_acceleration": [0.0, 0.0, 0.0],
    "gyroscope": [0.0, 0.0, 0.0], "magnetic_field": [20.0, -5.0, -40.0], "pressure": [1013.25], "light": [300.0],
    "proximity": [5.0], "game_rotation_vector": [0.0, 0.0, 0.0, 1.0], "rotation_vector": [0.0, 0.0, 0.0, 1.0],
}


def fake_values(t: Template, k: int) -> dict:
    """Typical values plus a slow, small wave (about ±0.5) so the board sees them change."""
    out = {}
    for src in t.sources:
        base = TYPICAL.get(src.rsplit(".", 1)[-1], [1.0] * 8)
        out[src] = [(base[i] if i < len(base) else 1.0) + 0.5 * math.sin(k / 50 + i) for i in range(16)]
    return out


class Run:
    """Frames sent and what the board said, for the verdict."""

    def __init__(self, t: Template):
        self.t, self.k, self.sent, self.reports, self.sent_accel, self._buf = t, 0, 0, [], [], b""

    def next_frame(self) -> bytes:
        values = fake_values(self.t, self.k)
        if "accelerometer" in values:
            self.sent_accel.append(values["accelerometer"][:3])
        frame = self.t.encode(values, self.k)
        self.k += 1
        self.sent += 1
        return frame

    def heard(self, data: bytes):
        self._buf += data
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            text = line.decode(errors="replace").strip()
            if text:
                print("  board:", text)
                self.reports.append(text)

    def verdict(self) -> int:
        m = next((re.search(r"frames=(\d+) bad=(\d+)", r) for r in reversed(self.reports) if "frames=" in r), None)
        if not m:
            print(f"SENT {self.sent} frames, not verified: the board reported no 'frames=… bad=…' line. Check the board's own behaviour.")
            return 0
        frames, bad = int(m.group(1)), int(m.group(2))
        ok = frames > self.sent * 0.5 and bad == 0
        print(f"Sent {self.sent}, board counted {frames} good and {bad} bad")
        # The examples also report the accelerometer (× 100); compare when the template sends it.
        v = next((re.search(r"accel_x100=(-?\d+),(-?\d+),(-?\d+)", r) for r in reversed(self.reports) if "accel_x100=" in r), None)
        if v and "accelerometer" in self.t.sources:
            accel = [int(v.group(i)) for i in (1, 2, 3)]
            # The report is up to 1 s old, so look for the frame it came from: same int16 values exactly.
            match = any([math.floor(x * 100 + 0.5) for x in e] == accel for e in self.sent_accel)
            print(f"Board's last accelerometer (x100) {accel}: {'matches a frame that was sent' if match else 'matches no frame sent'}")
            ok = ok and match
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1


def run_serial(t: Template, port: str, seconds: float) -> int:
    import serial

    s = serial.Serial(port, t.baud, timeout=0)
    s.dtr, s.rts = True, False  # like the phone: DTR on, RTS off (RTS alone resets an ESP32)
    time.sleep(1.5)  # a board that resets on connect needs a moment
    s.reset_input_buffer()
    print(f"Sending {t.name}: {t.size}-byte frames at {t.rate_hz:g} Hz for {seconds:g} s")
    r, period = Run(t), 1 / t.rate_hz
    end, nxt = time.time() + seconds, time.time()
    while time.time() < end:
        s.write(r.next_frame())
        r.heard(s.read(4096))
        nxt += period
        time.sleep(max(0.0, nxt - time.time()))
    s.close()
    return r.verdict()


async def run_ble(t: Template, name: str, seconds: float) -> int:
    import asyncio

    from bleak import BleakClient, BleakScanner

    print(f"scanning for {name!r}...")
    device = await BleakScanner.find_device_by_name(name, timeout=10)
    if device is None:
        print(f"No BLE device called {name!r} (is it advertising, and not connected to the phone?)")
        return 1
    r = Run(t)
    ble = t.raw.get("ble")
    targets = [(ble["service"], ble["characteristic"], None)] if ble else UART_SERVICES
    async with BleakClient(device) as client:
        write = notify = None
        for svc, wr, nt in targets:
            service = client.services.get_service(svc.lower())
            if service:
                write = service.get_characteristic(wr.lower())
                notify = service.get_characteristic(nt.lower()) if nt else None
                break
        if write is None:
            print("The board has no Nordic UART or FFE0 service (or the one the template names)")
            return 1
        if notify is not None and "notify" in notify.properties:
            await client.start_notify(notify, lambda _, data: r.heard(bytes(data)))
        no_response = "write-without-response" in write.properties
        print(f"connected (MTU {client.mtu_size}); sending {t.name}: {t.size}-byte frames for {seconds:g} s")
        end, period = time.time() + seconds, 1 / t.rate_hz
        while time.time() < end:
            await client.write_gatt_char(write, r.next_frame(), response=not no_response)
            await asyncio.sleep(period)
        await asyncio.sleep(1.5)  # the board's next report
    return r.verdict()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--port", help="serial port, e.g. COM3")
    where.add_argument("--ble", help="BLE device name, e.g. 'Robot NUS'")
    ap.add_argument("--template", required=True)
    ap.add_argument("--seconds", type=float, default=6)
    a = ap.parse_args()
    t = Template.load(a.template)
    if a.port:
        return run_serial(t, a.port, a.seconds)
    import asyncio

    return asyncio.run(run_ble(t, a.ble, a.seconds))


if __name__ == "__main__":
    sys.exit(main())
