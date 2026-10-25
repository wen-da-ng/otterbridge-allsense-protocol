"""Play the phone towards a board on a USB serial port (compact protocol), from the PC.

    allsense-fake-serial --port COM3 --seconds 6

The board must run a sketch using AllSenseSerial (e.g. examples/USBQuickstart) and be plugged
into the PC. Prints what the board sends (HELLO, SUBSCRIBE, HEARTBEAT) and streams a slowly
rotating fake tilt at 50 Hz to whatever it subscribes to, so its LED should cycle colours.
Also pings the board like the app's link test and reports the round trip (PONG).
Close the Arduino Serial Monitor first.
"""

import argparse
import math
import time

try:
    import serial
except ImportError:  # optional extra
    raise SystemExit('allsense-fake-serial needs pyserial: pip install "allsense-testkit[serial]"')

from . import compact as ac


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True, help="serial port, e.g. COM3 or /dev/ttyUSB0")
    ap.add_argument("--seconds", type=float, default=6)
    a = ap.parse_args()

    reader, seen, subscribed, seq = ac.Reader(), [], {}, 0
    ping_sent, rtts = {}, []
    with serial.Serial(a.port, 115200, timeout=0.02) as s:
        s.dtr, s.rts = True, False  # RTS without DTR would reset an ESP32
        s.write(ac.frame(ac.hello("pc-fake-phone")))
        start = time.time()
        while time.time() - start < a.seconds:
            for p in reader.feed(s.read(512)):
                seen.append(ac.describe(p))
                if p[0] == ac.HELLO:
                    s.write(ac.frame(ac.hello("pc-fake-phone")))
                elif p[0] == ac.SUBSCRIBE:
                    subscribed[p[1]] = p[6:].decode(errors="replace")
                    s.write(ac.frame(ac.status(p[1], 0)))
                    if not ping_sent:
                        ping_sent[1234] = time.perf_counter()
                        s.write(ac.frame(ac.ping(1234)))
                elif p[0] == ac.PONG and len(p) >= 5:
                    token = int.from_bytes(p[1:5], "little", signed=True)
                    if token in ping_sent:
                        rtts.append((time.perf_counter() - ping_sent.pop(token)) * 1000)
            t = time.time()
            for sid in subscribed:
                s.write(ac.frame(ac.data(sid, seq, int(t * 1e6), 3, (6 * math.sin(t), 6 * math.cos(t), 6.0))))
            seq += 1 if subscribed else 0
            time.sleep(0.02)
    print("board -> phone:")
    for line in dict.fromkeys(seen):
        print("  ", line)
    print(f"sent {seq} data frames per stream; corrupt frames received: {reader.corrupt}")
    print(f"ping round trip: {rtts[0]:.1f} ms" if rtts else "ping: no PONG (board library older than the link test?)")


if __name__ == "__main__":
    main()
