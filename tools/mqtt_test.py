"""A local MQTT broker plus a listener, to test the app's MQTT link without any MQTT hardware.

    tools/.venv-mqtt/Scripts/python tools/mqtt_test.py --seconds 20

Setup once:  <python> -m venv tools/.venv-mqtt && tools/.venv-mqtt/Scripts/pip install amqtt paho-mqtt

The phone reaches the broker through adb (works over Wi-Fi adb too):  adb reverse tcp:1883 tcp:1883
Then in the app's MQTT card, set the broker to tcp://127.0.0.1:1883 and start streaming.

It prints what arrives on allsense/# and checks: status "online", a catalog, stream messages with
t/time/seq/v, and at the end how many messages per topic and their rate. With --check-offline, it
also waits for "offline" when you stop streaming. Exit code 0 = everything arrived.
"""

import argparse
import asyncio
import json
import sys
import threading
import time
from collections import defaultdict


def listen(port: int, seconds: float, want_offline: bool, command: str = None):
    import paho.mqtt.client as mqtt

    seen = defaultdict(list)  # topic -> [(arrival, payload)]
    status = []
    done = threading.Event()

    def on_message(_c, _u, msg):
        text = msg.payload.decode(errors="replace")
        if msg.topic.endswith("/cmd/result"):
            print(f"  command result: {text}")
            seen[msg.topic].append((time.time(), text))
            return
        if msg.topic.endswith("/cmd"):
            return  # our own command
        if msg.topic.endswith("/status"):
            status.append(text)
            if text == "online" and command:
                prefix = msg.topic[: -len("/status")]
                print(f"  sending command to {prefix}/cmd: {command}")
                _c.publish(f"{prefix}/cmd", command, qos=1)
            print(f"  {msg.topic} = {text}{' (retained)' if msg.retain else ''}")
            if want_offline and text == "offline" and "online" in status:
                done.set()
        elif msg.topic.endswith("/catalog"):
            streams = json.loads(text).get("streams", [])
            print(f"  {msg.topic}: {len(streams)} streams in the catalog{' (retained)' if msg.retain else ''}")
            seen[msg.topic].append((time.time(), text))
        else:
            if not seen[msg.topic]:
                print(f"  first on {msg.topic}: {text[:160]}")
            seen[msg.topic].append((time.time(), text))

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="allsense-test-listener")
    c.on_message = on_message
    c.connect("127.0.0.1", port)
    c.subscribe("allsense/#")
    c.subscribe("+/+/status")
    c.loop_start()
    print(f"Listening on allsense/# for {seconds:g} s...")
    if want_offline:
        print("Stop streaming in the app when you're ready; waiting for 'offline'.")
        done.wait(seconds)
    else:
        time.sleep(seconds)
    c.loop_stop()
    c.disconnect()
    return seen, status


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--seconds", type=float, default=20)
    ap.add_argument("--check-offline", action="store_true")
    ap.add_argument("--command", help='JSON command to send once the phone is online, e.g. {"command":"vibrate","ms":300}')
    a = ap.parse_args()

    from amqtt.broker import Broker

    config = {
        "listeners": {"default": {"type": "tcp", "bind": f"0.0.0.0:{a.port}"}},
        "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
    }
    loop = asyncio.new_event_loop()
    broker = Broker(config, loop=loop)
    loop.run_until_complete(broker.start())
    threading.Thread(target=loop.run_forever, daemon=True).start()
    print(f"Broker on 0.0.0.0:{a.port}")

    seen, status = listen(a.port, a.seconds, a.check_offline, a.command)
    ok = "online" in status
    streams = {t: msgs for t, msgs in seen.items() if not t.endswith(("/catalog", "/cmd/result"))}
    if a.command:
        results = [json.loads(m[1]) for t, msgs in seen.items() if t.endswith("/cmd/result") for m in msgs]
        print(f"  command results: {results or 'none'}")
        ok_cmd = any(r.get("ok") for r in results)
    print("\nSummary:")
    print(f"  status: {status or 'nothing'}")
    print(f"  catalog: {'yes' if any(t.endswith('/catalog') for t in seen) else 'no'}")
    for topic, msgs in sorted(streams.items()):
        last = json.loads(msgs[-1][1])
        span = msgs[-1][0] - msgs[0][0]
        rate = (len(msgs) - 1) / span if span > 0 else 0
        good = all(k in last for k in ("t", "time", "seq", "v"))
        ok = ok and good
        print(f"  {topic}: {len(msgs)} messages, {rate:.1f}/s, seq {json.loads(msgs[0][1])['seq']}..{last['seq']}, fields ok: {good}")
    ok = ok and bool(streams) and any(t.endswith("/catalog") for t in seen)
    if a.check_offline:
        ok = ok and "offline" in status
    if a.command:
        ok = ok and ok_cmd
    print("PASS" if ok else "FAIL")
    loop.call_soon_threadsafe(loop.stop)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
