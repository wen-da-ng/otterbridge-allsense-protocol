---
title: MQTT reference
description: "MQTT reference: topics, payloads, retained catalog and status, commands, and testing without a broker."
---

# MQTT reference

Topics, payloads and testing. To set it up, start with [Get started → MQTT](https://docs.allsense.otterbridge.org/get-started/mqtt/).
{ .lead }

The app can publish streams to an MQTT broker while streaming is on: **Home → Connect → MQTT**. Turn on *Publish to a broker*, enter the broker, choose the streams and a rate, and **Save**. It reconnects by itself if the broker goes away.

## The broker

MQTT needs a broker: a server that the phone publishes to and anything else subscribes from. It isn't hardware; it runs on a computer.

| Where it runs | Broker field in the app |
|---|---|
| A PC on the same network (e.g. Mosquitto) | `tcp://<PC's IP>:1883`, e.g. `tcp://192.168.1.20:1883`. The PC's firewall must allow port 1883. |
| Raspberry Pi / Home Assistant (Mosquitto add-on) | `tcp://<its IP>:1883`, with the add-on's username and password |
| A cloud broker (HiveMQ Cloud, EMQX Cloud…) | `ssl://<host>:8883`, with your account's username and password |

`tcp://` is plain, `ssl://` is TLS. The password is kept in the app's private storage.

## Topics and messages

With the default prefix `allsense/<device>` (change it in the card):

| Topic | Payload | Retained |
|---|---|---|
| `allsense/<device>/<category>/<name>` | one message per sample: `{"t":415062462972699,"time":1792239094.642025,"seq":0,"v":[-0.76,4.08,8.90]}` | no |
| `allsense/<device>/<category>/<name>/status` | why a stream isn't sending, for people: `{"state":"refused","reason":"Needs precise location: Sensors → Location → Allow"}`, `{"state":"not_shared","reason":"…"}`, or `{"state":"streaming"}` once samples flow | yes |
| `allsense/<device>/catalog` | the stream list, the same JSON as the protocol's `catalog` (fields, units…) | yes |
| `allsense/<device>/status` | `online` when connected, `offline` when streaming stops or the phone drops off (last will) | yes |
| `allsense/<device>/cmd` (you publish) | a command: `{"command":"vibrate","ms":200,"id":1}` ([PROTOCOL.md](PROTOCOL.md#commands), "Commands") | no |
| `allsense/<device>/cmd/result` | its result: `{"op":"command_result","id":1,"command":"vibrate","ok":true}` | no |

- `t`: the sample's timestamp in ns on the phone's boot clock (as in the protocol); `time`: the same moment in Unix seconds; `seq`: counts up per stream, so gaps mean lost messages; `v`: the values, `null` when missing. The order of `v` is the stream's `fields` in the catalog ([PROTOCOL.md](PROTOCOL.md#streams), "Streams").
- Category and name are as in the app, e.g. `allsense/phone/sensors/accelerometer`, `allsense/phone/gnss/position`, `allsense/phone/battery/battery`.
- Subscribing to `allsense/<device>/#` also brings each stream's `…/status`: skip topics ending in `/status` (and `catalog`, `cmd…`) when you only want samples.
- QoS 0 for samples (newest data matters, not every sample), QoS 1 for status and catalog.
- Continuous streams publish at the chosen rate; event streams (GNSS, light…) on every event. Sharing (**Home → Connect → Browser → Streams it may send**) applies: a stream that isn't shared over Network isn't published.

Commands are off until allowed in the app (**Robot → Robot can control the phone**): anyone who can publish to your broker could otherwise make the phone vibrate, light up or speak.

## Using it

- **See it:** MQTT Explorer (desktop app) or `mosquitto_sub -h <broker> -t 'allsense/#' -v`.
- **Home Assistant / Node-RED:** subscribe to a stream topic and read `value_json.v[0]` (e.g. battery level) or the field you need.
- **Python:** any MQTT client, e.g. paho-mqtt: subscribe to `allsense/<device>/#` and `json.loads(msg.payload)`.

## Testing without a broker

`tools/mqtt_test.py` in the [protocol repository](https://github.com/wen-da-ng/otterbridge-allsense-protocol) runs a broker and a listener on the PC and checks what arrives (run it from that repository's folder):

```
<python> -m venv tools/.venv-mqtt && tools/.venv-mqtt/Scripts/pip install amqtt paho-mqtt   # once
adb reverse tcp:1883 tcp:1883                     # the phone's 127.0.0.1:1883 → the PC (also over Wi-Fi adb)
tools/.venv-mqtt/Scripts/python tools/mqtt_test.py --seconds 120 --check-offline
```

In the app: broker `tcp://127.0.0.1:1883`, choose streams, Save, Start streaming, then Stop. It prints PASS when status online/offline, the catalog and the stream messages all arrived. `--command '{"command":"vibrate","ms":300}'` also sends a command after the phone connects and prints the result.
