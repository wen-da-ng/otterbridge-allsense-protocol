---
title: Protocol
description: "The wire formats: JSON over WebSocket, video and audio over HTTP, and the compact binary protocol over USB and Bluetooth LE."
---

# AllSense Protocol, version 0

Everything a client needs to talk to the phone, in any language.
{ .lead }

!!! note "Experimental"
    Version 0 may still change; compatibility starts with version 1. The specification is MIT licensed, so anyone can implement it.

## Connecting

The phone runs an HTTP + WebSocket server once **Start streaming** is tapped (Home).

| | |
|---|---|
| Port | `8765` (default) |
| Dashboard | `http://<phone>:8765/?token=<token>` |
| WebSocket | `ws://<phone>:8765/ws?token=<token>` |
| Discovery | DNS-SD service `_allsense._tcp`, TXT: `device`, `protocol`, `path` |

Add `&catalog=none` to the WebSocket URL to skip the automatic catalog (it is ~20 KB on a real phone, more than small devices accept in one message; the ESP32 WebSocket library's limit is 15 KB). Ask for it later with `{"op":"catalog"}` if needed.

The **token** is shown in the app and in its QR code. Requests without it are rejected (HTTP 401, or WebSocket close code 1008).

Reachable over Wi-Fi, the phone's own hotspot, USB tethering, or USB with `adb forward tcp:8765 tcp:8765` (then use `localhost`).

## Messages

Every message is one JSON object in a WebSocket **text** frame, with an `op` field.

### Phone → client

**`hello`**: sent first.
```json
{"op":"hello","protocol":0,"app":"AllSense","app_version":"0.1.0","device":"phone",
 "clock":"boottime_ns","boot_to_unix_ns":1760371200000000000}
```
Sample timestamps `t` are nanoseconds on the phone's boot clock (the hardware sensor timestamp). `t + boot_to_unix_ns` gives Unix time in ns. That conversion is accurate to the phone's wall clock; use `time_sync` for your own clock.

**`catalog`**: sent after `hello` (unless you connected with `catalog=none`), and again when you send `{"op":"catalog"}`.
```json
{"op":"catalog","device":"phone","streams":[
  {"topic":"allsense.phone.sensors.accelerometer","name":"accelerometer",
   "id":"sensors/1/stmicro/lsm6dso_accelerometer/n/0","category":"sensors","kind":"vector",
   "type":"Accelerometer","sensor_type":1,"hardware":"LSM6DSO Accelerometer","vendor":"STMicro",
   "fields":["x","y","z"],"unit":"m/s²","max_range":78.45,"reporting":"continuous","max_rate_hz":500.0,
   "wake_up":false,"basic":true}
]}
```
- `topic` = `allsense.<device>.<category>.<name>`. The user can rename `device` and `name`.
- `id` is stable across renames and reboots. Store it if you need to find the same hardware again.
- `category` is `sensors`, `gnss`, `battery`, `wifi` or `cellular` (see **Streams** below).
- `stream_type` says what the values are, for programs: Android's sensor string type (`android.sensor.accelerometer`) for sensors, `allsense.gnss.position` etc. for the others. `type` is for display.
- `sensor_type` is Android's numeric sensor type (`Sensor.TYPE_*`, e.g. 1 accelerometer, 4 gyroscope); vendor types are ≥ 65536. `null` for streams that aren't Android sensors.
- `max_range` is the sensor's maximum value, in `unit`.
- `fields` labels the values. A sample can have more values than labels; call the extras `v3`, `v4`, …
- `units` has one unit per field (`""` when unitless). `unit` is the shared unit when every field has the same one, else `""`.
- `reporting`: `continuous`, `on change`, `one shot` or `special trigger`. Only continuous streams honour `rate_hz`; the others send every event.
- `basic: false` marks what the app's Basic mode hides: vendor-specific sensors, wake-up copies and raw variants.
- `shared: false` marks streams the user doesn't share over the network (see **Sharing** below). The phone sends the catalog again when that changes.

**`data`**: one sample.
```json
{"op":"data","topic":"allsense.phone.sensors.accelerometer","seq":812,"t":123456789000,"v":[0.12,9.79,0.33],"acc":3}
```
- `seq` counts up per subscription, so gaps mean dropped samples. If the link is too slow, the phone drops the **oldest** queued messages, so you always get fresh data.
- `v` values can be `null` (not a number).
- `acc` is Android's sensor accuracy: 3 high, 2 medium, 1 low, 0 unreliable, −1 no contact.

**`subscribed`**: confirms a subscription. Also sent later for a `not_shared` subscription once the user shares the stream.
```json
{"op":"subscribed","topic":"allsense.phone.sensors.accelerometer","rate_hz":50}
```
`rate_hz` is `null` for event sensors.

**`status`**: a subscription state change. `state` is `armed` (waiting for the first reading: a one-shot sensor's event, a GNSS fix), `refused` (no data will come; `reason` says why: Android won't deliver the sensor, location access is missing, Location is off) or `not_shared` (the user doesn't share it over this link).
```json
{"op":"status","topic":"…","state":"refused","reason":"Android won't deliver this sensor to apps"}
```

**`time_sync`**: reply to yours (see below).

**`error`**: e.g. `{"op":"error","message":"Unknown topic \"…\""}`.

**`ping`**: `{"op":"ping","id":17}`, sent by the app's link test. Answer at once with `{"op":"pong","id":17}`.

**`fill`**: `{"op":"fill","pad":"xxxx…"}`, link test padding (about 4 KB). Ignore it.

### Client → phone

| Message | Effect |
|---|---|
| `{"op":"hello","client":"my_robot"}` | Optional. Names you in the app's client list. |
| `{"op":"subscribe","topics":["…"],"rate_hz":100}` | Start (or change the rate of) streams. Default 50 Hz, max 1000 Hz, limited by the sensor. A single `"topic"` also works. |
| `{"op":"unsubscribe","topics":["…"]}` | Stop streams. `{"op":"unsubscribe","all":true}` stops all of them. |
| `{"op":"catalog"}` | Ask for the catalog again (e.g. after the user renamed something). |
| `{"op":"time_sync","t0":<your clock>}` | The phone replies with `t0` unchanged, plus `t1` (receive) and `t2` (send) in boot-clock ns. |
| `{"op":"pong","id":<the ping's id>}` | Answer to the phone's `ping`. |

### Clock sync
With your clock at reply `t3`:
- round trip = `(t3 − t0) − (t2 − t1)` (convert to the same units)
- phone boot clock ≈ your clock at `t0 + round_trip/2` ↔ `t1`

Repeat it every few seconds and keep the sample with the smallest round trip.

## Streams

Besides Android's sensors (category `sensors`, one per hardware sensor), every phone offers these. Default names are unique, so boards can subscribe by name alone:

| Name | Category | `stream_type` | Values | Units | Reporting |
|---|---|---|---|---|---|
| `position` | `gnss` | `allsense.gnss.position` | latitude, longitude, altitude, accuracy, speed, bearing, vertical accuracy | °, °, m, m, m/s, °, m | on change (each fix, up to 10 Hz) |
| `satellites` | `gnss` | `allsense.gnss.satellites` | visible, used in fix, mean C/N0 of used, best C/N0 | –, –, dB-Hz, dB-Hz | on change (~1 Hz) |
| `battery` | `battery` | `allsense.battery` | level, voltage, temperature, current, charging (1/0) | %, V, °C, mA, – | continuous (≤ 10 Hz) |
| `wifi_signal` | `wifi` | `allsense.wifi.signal` | RSSI, link speed, frequency | dBm, Mbps, MHz | continuous (≤ 5 Hz) |
| `cell_signal` | `cellular` | `allsense.cellular.signal` | strength, level | dBm, 0–4 | continuous (≤ 1 Hz) |

- Missing values are `null` (JSON) or NaN (compact): no fix yet, bearing while standing still, Wi-Fi not connected.
- **GNSS** needs the app's location access and Location turned on, or the subscription gets `refused` with the reason. Until the first fix it's `armed`. Timestamps are the fix time.
- **Precision:** JSON sends latitude and longitude as full doubles. Compact DATA sends float32, about 1 m at these magnitudes; a frame template with `"type": "i32", "scale": 10000000` sends exact degrees × 10⁷ ([TEMPLATES.md](TEMPLATES.md)).
- Battery current's sign follows the phone (positive while charging on most).

### Robot frame (`robot` category)

When the user sets how the phone is mounted (app: **Robot → Mount on the robot**: which phone axis points to the robot's front and which up), the main motion sensors are also streamed in the robot's axes, ROS REP-103: **x forward, y left, z up**. The phone's own streams don't change.

| Name | Same as | Values |
|---|---|---|
| `accelerometer`, `gyroscope`, `magnetic_field`, `gravity`, `linear_acceleration` | the phone's sensor (same `sensor_type` and `stream_type`, units) | x, y, z in the robot's axes |
| `rotation_vector`, `game_rotation_vector` | the phone's sensor | the robot's orientation, quaternion x, y, z, w (robot → East-North-Up) |
| `attitude` (`stream_type` `allsense.robot.attitude`) | – | roll (> 0: right side down), pitch (> 0: nose down), yaw (from East, > 0: turned left), heading (compass, clockwise from North; `null` without a compass-based rotation vector), all in ° |

- They share names with the phone's streams, so a plain name still means the phone's own: subscribe to **`robot.accelerometer`** (category and name), the full topic `allsense.<device>.robot.accelerometer`, or the ID `robot/accelerometer`. Boards and frame templates can use `robot.attitude` too.
- They exist only while a mount is set; changing the mount applies to running streams at once (clients see new streams after asking for the catalog again).

### Vision (`vision` category): AprilTags

With **Robot → AprilTags** turned on (off by default), the stream **`apriltag`** (`stream_type` `allsense.vision.apriltag`, topic `allsense.<device>.vision.apriltag`) reports the AprilTags one camera sees, using the AprilRobotics detector on the phone. Detection runs only while someone subscribes, sharing the camera with video viewers. **One sample per tag per frame** (several tags in a frame: several samples with the same `t`; no tag in view: no samples):

| Field | Unit | Meaning |
|---|---|---|
| `id` | | The tag's number in its family |
| `u`, `v` | 0–1 | Its centre across and down the camera image (the image as streamed, in the sensor's orientation) |
| `x`, `y`, `z` | m | Its centre in the camera's frame: x right, y down, z out of the lens |
| `distance` | m | Straight-line distance |
| `bearing` | ° | Left (> 0) or right (< 0) of straight ahead |
| `yaw` | ° | How far the tag is turned about its vertical axis (0: facing the camera; > 0: its right edge is nearer) |
| `margin` | | Detection quality: higher is surer, below ~30 is shaky |

- `x`…`yaw` need the **tag size** (the black square's edge) set in the app; until then they're `null`.
- Settings: camera, family (`tag36h11` default, `tag25h9`, `tag16h5`, `tagStandard41h12`, `tagCircle21h7`), tag size, picture size (640×480 or 1280×720) and rate (5–30 fps). Changes apply to running subscriptions.
- Distance uses the lens's factory calibration when it has one, else its focal length: expect a few percent of error; calibrate your own camera for precise work.
- It's a plain stream on purpose: boards can subscribe by `vision.apriltag`, and your own detector (on the video stream, elsewhere) can produce the same fields.

## Camera

Cameras are in the catalog with `"category": "camera"`, `"kind": "image"` and `"stream_type": "allsense.camera.mjpeg"`, plus:
- `url`: where the video is, e.g. `/camera/back_24mm.mjpg` (name as set in the app).
- `facing`: `back`, `front` or `external`.
- `sensor_orientation`: degrees (0, 90, 180, 270). Frames are as the sensor sees them; rotate them clockwise by this to show them upright.

Video doesn't go over the WebSocket: subscribing to a camera topic is answered with `status` `refused` and a reason naming the URL. Instead, on the same host, port and token:

| Request | Answer |
|---|---|
| `GET /camera/<name>.mjpg?token=…` | Live video: `multipart/x-mixed-replace; boundary=allsenseframe`. Each part is one JPEG with `Content-Length`, `X-Timestamp-Ns` (the frame's sensor time, boot clock, like samples' `t`) and `X-Size` (`640x480`). Browsers show it in an `<img>`. |
| `GET /camera/<name>.jpg?token=…` | One JPEG. |
| `GET /camera/<name>.h264?token=…` | H.264 from the phone's hardware encoder, multipart like MJPEG: each part is one access unit in Annex B form (`Content-Type: video/h264`), with `X-Timestamp-Ns`, `X-Keyframe` (1/0) and `X-Size`. Keyframes come every second and carry SPS/PPS, so decoding can start at any of them; a new viewer starts at one. `bitrate=1000000` (bits/s). The catalog's `h264_url` gives the path. |
| `GET /camera/<name>.h264?raw=1&token=…` | The same as a plain Annex B byte stream, for players: `ffplay -f h264 "<url>"`, VLC, OpenCV (`cv2.VideoCapture(url)`). |

Query options: `size=640x480` (the largest size the camera has within it; default 640×480), `fps=15` (1–60), `quality=70` (JPEG, 10–95), `zoom=1` (Android's zoom ratio, within the catalog's `zoom_range`). The first viewer of a camera sets its size, quality and zoom; later viewers share the same capture at their own `fps` (they get the newest frame, never a backlog).

**Lenses through zoom.** Phones often let apps open only a few cameras directly; the other lenses sit behind a multi-lens ("logical") camera and are chosen by zoom. On the developer's Samsung, `back_22mm` has `zoom_range` 0.6–10: 0.6 uses the 13 mm ultra-wide, about 3 the 61 mm telephoto, about 5 the 113 mm one. The phone picks the lens (in low light it may crop the main lens instead). Cameras the phone lists but won't let apps open answer 503 "No camera device with ID … available".

Errors come back as plain text with a status: 404 (no such camera), 403 (not shared over Network: Home → Connect → Browser → Streams it may send), 503 (no camera access, camera in use by another app or the app's own Sensors → Cameras page, or it didn't start within 8 s).

- The camera runs only while someone watches, and Android shows its camera indicator meanwhile.
- One app can use a camera at a time: the app's Sensors → Cameras page and a stream of the same camera exclude each other.
- **Several cameras at once** depends on the phone's camera hardware: each lens excludes some others (on the developer's Samsung, the ultra-wide back camera can't run with the second front camera). `concurrent_with` in the catalog lists the cameras Android *guarantees* can run alongside one; other pairs may work or be refused with a 503 that names the camera in the way.
- Each viewer appears under **Home → Connect → Browser** (with Disconnect).
- **H.264 vs MJPEG:** H.264 needs about a fifth of the bandwidth (1 Mbit/s vs about 5 for 640×480 at 15 fps) but every viewer gets every frame (frames depend on earlier ones), at the capture's rate; a viewer that falls behind skips to the next keyframe. MJPEG viewers each get their own rate. Both can watch the same camera at once (the first H.264 viewer briefly restarts the capture to add the encoder).

## Microphone

Microphones are in the catalog with `"category": "mic"`, `"kind": "audio"`, `"stream_type": "allsense.mic.pcm16"`, `url` (e.g. `/mic/mic.wav`) and `sample_rates`. Each also has a level stream named `<name>_level` (category `mic`, values `rms` and `peak` in dBFS, up to 50 Hz) that works like any other stream, on every link.

| Request | Answer |
|---|---|
| `GET /mic/<name>.wav?token=…&rate=16000` | Live audio: a WAV header (sizes set to the maximum: endless), then mono 16-bit little-endian PCM. `X-Timestamp-Ns` is the first sample's time on the phone's boot clock; after it, samples are back to back at `X-Sample-Rate`. Rates: 8000, 16000 (default), 22050, 44100, 48000; the first listener sets it. |

Errors as for cameras: 404, 403 (not shared over Network), 503 (no microphone access, or it's in use). The microphone records only while someone listens (Android shows its indicator); a JSON subscribe to a microphone's topic is refused with the URL.

## Commands

Clients can ask the phone to do things, if the user allows it (**Robot → Robot can control the phone**; off by default). Over the WebSocket:

```json
{"op":"command","id":1,"command":"vibrate","ms":200}
{"op":"command_result","id":1,"command":"vibrate","ok":true}
```

Over MQTT, the same JSON (without `op`) on `<prefix>/cmd`; results on `<prefix>/cmd/result` ([MQTT.md](MQTT.md)).

| Command | Arguments | Does |
|---|---|---|
| `ping` | | Answers with `time_unix` |
| `vibrate` | `ms` (10–5000, default 200) | Vibrates |
| `torch` | `on` (true/false) | The main flash; fails while that camera is streaming |
| `tone` | `ms` (default 200) | A beep |
| `say` | `text` (≤ 300 characters) | Text-to-speech in the phone's language |
| `record` | `action`: `start` (with optional `streams`: names, `rate_hz`) or `stop` | Recording ([RECORDING.md](RECORDING.md)); it keeps going if streaming stops |
| `display` | `face` (`happy`, `sad`, `neutral`, `surprised`, `thinking`, `sleepy`, `angry`) and/or `text` (≤ 200 characters), optional `color`, `background` (`"red"`, `"#ff8800"`, `"#80ff8800"`), `brightness` (0–1); or `action`: `clear` | Full-screen face or text, e.g. a robot's face or status panel. Wakes the screen, shows over the lock screen and keeps the screen on until cleared (or a long-press on the phone). Sending it again updates what's shown. With the app in the background it needs **Display over other apps** (Robot → Robot can control the phone → Screen from the background → Allow) |
| `volume` | `level` (0–1; leave out to just read it), `stream`: `media` (default), `notification` or `alarm` | Sets the volume; answers with the resulting `level` (phones have about 15 steps) |
| `sound` | `name`: a saved sound, or the phone's own `notification` (default), `alarm` or `ringtone`; `ms` (stop after; the phone's own default to 5000), `loop` (saved sounds). Or `action`: `stop`, `list`, `delete` (with `name`) or `save` (with `name`, base64 `data`, optional `format`) | Plays a sound; one at a time. Save bigger files over HTTP (below): the WebSocket takes messages up to 64 KB |
| `camera` | `camera` (name), then any of: `ev` (exposure compensation, EV), `iso` + `exposure_ms` (manual exposure) or `exposure`: `auto`, `ae_lock`, `focus` (`auto`, `infinity` or a distance in metres), `white_balance` (`auto`, `daylight`, `cloudy`, `shade`, `twilight`, `incandescent`, `fluorescent`, `warm-fluorescent`), `awb_lock`, `reset` (all automatic) | Exposure, focus and white balance of that camera's capture. Every viewer of the camera sees them; kept until the app restarts. Answers with `settings` (current) and `supports` (ranges, `min_focus_m`, white balances, locks) — send just `camera` to read them. Values are clamped to what the lens can do |

A failure answers `"ok": false` with `error` (e.g. commands not allowed, unknown command, no flash).

**Saved sounds over HTTP** (same port and token; refused with 403 while Commands is off):
- `PUT /sounds/<name>.<format>?token=…` with the file as the body saves it (replacing one of that name). Names: 1–40 of `a-z 0-9 _ -`, not `notification`/`alarm`/`ringtone`. Formats: wav, mp3, ogg, m4a, aac, flac, opus; up to 10 MB, 100 sounds. Answers `{"ok":true,"name":…,"format":…,"bytes":…}`, or 400 with the reason.
- `GET /sounds?token=…` lists them: `{"sounds":[{"name":"alarm","built_in":true},…,{"name":"beep","format":"wav","bytes":12044}]}`.
- e.g. `curl -T beep.wav "http://<phone>:8765/sounds/beep.wav?token=…"`, then `{"command":"sound","name":"beep"}`.

## Link test
The **Test** button next to a connected client (in its Connect guide) measures that client's link, in about 3 s:
1. **Round trip:** the phone sends up to five pings and times the answers (median). A client that doesn't answer the first one within 1 s gets "no ping reply".
2. **Throughput:** for 2.5 s the phone writes filler (`fill` / compact FILL) as fast as the link takes it, and counts the last 2 s. The slowest part sets the number: the radio, the cable, or how fast the client reads.

Streams on that link pause during the test. Clients only have to answer pings and ignore filler; both are new in v0, and older clients that ignore unknown messages keep working (they just show no round trip). The phone doesn't test boards set to a frame template.

## Sharing
The user picks, per kind of link (**Network** = this WebSocket, **USB**, **Bluetooth**), whether it shares every stream or only some (app: Home → Connect → that link's guide → Streams it may send → Choose). For a stream that isn't shared:
- A subscription is answered with `status` `not_shared` (compact: STATUS code 4). The phone **keeps** it and starts it, with `subscribed` (compact: STATUS 0), as soon as the user shares the stream. No need to resubscribe.
- If the user stops sharing a stream while it's streaming, the phone sends `not_shared` and stops its data. It resumes by itself the same way.
- Sharing follows the stable `id`, so renaming a stream doesn't change who receives it. New sensors aren't shared with an "only these" link.

## Frame templates
Boards with their own protocol don't speak either protocol here: the phone sends them frames described by a template file instead. See [TEMPLATES.md](TEMPLATES.md).

## Limits and notes
- One phone streams to many clients. Each client subscribes independently, and the phone runs each sensor at the fastest rate anyone asked for.
- JSON costs roughly 100 bytes per 3-axis sample, which is fine for hundreds of Hz over Wi-Fi or USB. Microcontroller links use the compact binary protocol below instead.
- Version 0 streams sensors, GNSS, battery, radio signal and microphone level (see **Streams**) over the WebSocket, cameras as MJPEG or H.264 over HTTP (see **Camera**) and microphone audio as WAV over HTTP (see **Microphone**).

---

# Compact protocol (serial links), version 0

For microcontrollers on a **USB serial** link (and later BLE). The phone is the USB host (e.g. a USB-C to USB-C cable) and powers the board. It's binary, checksummed and small: a 3-axis sample is a 23-byte frame. It's easy to parse on 8-bit boards. No token: plugging in the cable is the permission. It's active while streaming is started in the app.

## Framing

Every frame is `COBS(payload ‖ CRC16) 0x00`:
- **CRC16**: CRC-16/CCITT-FALSE (poly `0x1021`, init `0xFFFF`, no reflection, no final XOR) over the payload, appended little-endian. Check value: `"123456789"` → `0x29B1`.
- **COBS** (canonical Consistent Overhead Byte Stuffing) removes every `0x00`, so `0x00` always ends a frame. After noise, a receiver resynchronises at the next `0x00`. Frames that fail COBS or CRC are dropped silently.
- Payload ≤ 250 bytes. Byte 0 is the type. Multi-byte numbers are little-endian; floats are IEEE-754 binary32.
- Serial settings: 115200 8N1 (ignored by native-USB boards).

## Messages

| Type | Direction | Payload after the type byte |
|---|---|---|
| `0x01` HELLO | both | `u8 version (0)`, then UTF-8 name: the client's name, or the phone's device name |
| `0x02` SUBSCRIBE | board → phone | `u8 stream_id`, `f32 rate_hz`, UTF-8 stream name (as set in the app, e.g. `accelerometer`; the full topic or stable ID also work) |
| `0x03` UNSUBSCRIBE | board → phone | `u8 stream_id` (`0xFF` = all) |
| `0x04` STATUS | phone → board | `u8 stream_id`, `u8 code`, optional UTF-8 text. Codes: 0 subscribed, 1 unknown name, 2 refused by Android, 3 armed (one-shot sensor), 4 not shared over this link (see Sharing above; ≤ 47-character text) |
| `0x05` HEARTBEAT | both | (empty) |
| `0x06` PING | phone → board | `u32 token`. Answer with PONG (link test) |
| `0x07` PONG | board → phone | the PING's `u32 token`, unchanged |
| `0x08` FILL | phone → board | any bytes (link test padding, up to the payload limit). Ignore it |
| `0x10` DATA | phone → board | `u8 stream_id`, `u16 seq`, `u32 t_us`, `i8 accuracy`, `u8 n`, `n × f32` values |

- **The board picks `stream_id`** (any value 0–254) for each subscription, and the phone tags that stream's DATA with it. So the board never needs the catalog.
- `t_us` is the sensor's hardware timestamp in µs on the phone's boot clock, truncated to 32 bits (it wraps about every 71 minutes). Use differences between samples.
- `seq` is 16-bit, counting up per subscription; gaps mean lost samples.

## Session

1. When the link opens, the phone sends HELLO, then a HEARTBEAT whenever nothing else was sent for 1 s.
2. The board sends HELLO when it starts, and again every second until it hears the phone's HELLO. The phone answers every board HELLO with its own and **drops that board's old subscriptions** (the board restarted).
3. After the phone's HELLO, the board sends its SUBSCRIBEs. The phone answers each with a STATUS, then streams DATA.
4. If the board hears nothing for ~3 s, it treats the link as lost and goes back to step 2. This covers an unplugged cable, the phone stopping streaming, or the phone's USB resetting.

Unknown frame types must be ignored, so the protocol can grow.

Worked example (bytes in hex). SUBSCRIBE to `accelerometer` at 50 Hz as stream 1:
payload `02 01 00004842 616363656c65726f6d65746572`, frame on the wire `03020101124842616363656c65726f6d65746572b12100`.
DATA, stream 3, seq 513, t = 123456789 µs, accuracy 3, values (0, 1.5, −9.81):
frame `0b1003010215cd5b070303010101010109c03fc3f51cc18f6f00`.
PING with token 0x01020304: payload `06 04030201`; the PONG payload is `07 04030201`.

## BLE transport

The same compact frames also run over Bluetooth LE. The **board is the peripheral** and the phone connects to it as central, like USB where the phone is the host.

| | UUID | |
|---|---|---|
| Service | `a1150001-ae7a-4681-958d-74782a0d0f32` | advertised by the board; put the board's name in the scan response |
| RX | `a1150002-ae7a-4681-958d-74782a0d0f32` | phone → board, write without response |
| TX | `a1150003-ae7a-4681-958d-74782a0d0f32` | board → phone, notify |

- Both directions are a **byte stream**: frames may be split across or packed into BLE packets, and the `0x00` delimiters reassemble them. The phone requests MTU 247 and a high-priority connection interval (7.5–15 ms). The board should accept MTU 247 and may notify in chunks as small as 20 bytes.
- The phone only connects to boards the user approved under **Home → Connect → Microcontroller** (**Connect**), then reconnects automatically whenever the board is in range. While that screen is open, it scans for new boards by the service UUID.
- The session works exactly as over USB: HELLO, SUBSCRIBE, STATUS, DATA, HEARTBEAT.
