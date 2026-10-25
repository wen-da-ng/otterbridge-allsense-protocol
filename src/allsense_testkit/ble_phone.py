"""Play the phone towards an AllSense BLE board, over the PC's Bluetooth (compact protocol).

    allsense-fake-ble --seconds 5 [--serial COM3]

The board must run a sketch using AllSenseBLE (e.g. examples/BLEQuickstart) and must not be
connected to the phone (a connected board stops advertising). With --serial, the board's own
USB output is shown too. Needs `bleak` (and pyserial for --serial).
"""

import argparse
import asyncio
import math
import threading
import time

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # optional extra
    raise SystemExit('allsense-fake-ble needs bleak: pip install "allsense-testkit[ble]"')

from . import compact as ac


def tail_serial(port, stop, lines):
    import serial

    try:
        with serial.Serial(port, 115200, timeout=0.2) as s:
            s.dtr = True
            buf = b""
            while not stop.is_set():
                buf += s.read(256)
                *done, buf = buf.split(b"\n")
                lines.extend(l.decode("utf-8", "replace").strip() for l in done if l.strip())
    except Exception as e:  # noqa: BLE001 - just report it
        lines.append(f"(serial port unavailable: {e})")


async def main(a):
    stop, board_lines = threading.Event(), []
    if a.serial:
        threading.Thread(target=tail_serial, args=(a.serial, stop, board_lines), daemon=True).start()

    print("scanning for AllSense boards...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, adv: ac.BLE_SERVICE in [u.lower() for u in adv.service_uuids], timeout=10)
    if device is None:
        stop.set()
        print("No AllSense board found (is it advertising, and not connected to the phone?)")
        return
    print(f"found {device.name!r} at {device.address}")

    reader, seen, subscribed = ac.Reader(), [], asyncio.Event()
    sub_ids = []

    def on_notify(_, chunk: bytearray):
        for p in reader.feed(bytes(chunk)):
            seen.append(ac.describe(p))
            if p[0] == ac.SUBSCRIBE:
                sub_ids.append(p[1])
                subscribed.set()

    async with BleakClient(device) as client:
        print(f"connected, MTU {client.mtu_size}")
        await client.start_notify(ac.BLE_TX, on_notify)
        await client.write_gatt_char(ac.BLE_RX, ac.frame(ac.hello("pc-ble-phone")), response=False)
        await asyncio.wait_for(subscribed.wait(), 6)
        for sid in set(sub_ids):
            await client.write_gatt_char(ac.BLE_RX, ac.frame(ac.status(sid, 0)), response=False)
        sent, start = 0, time.time()
        while time.time() - start < a.seconds:
            t = time.time()
            for sid in set(sub_ids):
                await client.write_gatt_char(
                    ac.BLE_RX, ac.frame(ac.data(sid, sent, int(t * 1e6), 3, (6 * math.sin(t), 6 * math.cos(t), 6.0))),
                    response=False)
            sent += 1
            await asyncio.sleep(0.02)
        print(f"sent {sent} data frames in {a.seconds:g} s (Windows timers cap this near 30-60/s)")
    await asyncio.sleep(1.5)
    stop.set()
    print("board -> phone:")
    for line in dict.fromkeys(seen):
        print("  ", line)
    if board_lines:
        print("board's serial output:")
        for line in board_lines[-6:]:
            print("  ", line)


def cli():
    """allsense-fake-ble: a stand-in phone that connects to a BLE board."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=5)
    ap.add_argument("--serial", help="also show the board's USB output from this port, e.g. COM3")
    asyncio.run(main(ap.parse_args()))


if __name__ == "__main__":
    cli()
