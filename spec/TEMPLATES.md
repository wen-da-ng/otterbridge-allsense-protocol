---
description: "Make the phone send the exact binary frames your board already understands, described in a JSON file, with no code."
---

# Frame templates

Your board already has a protocol? The phone can speak it.
{ .lead }

!!! robot "For example"
    A robot's motor board expects `AA 55`, six 16-bit IMU values and an XOR checksum, 100 times a second. Describe that frame once in JSON; the phone sends it, and the firmware doesn't change.

A frame template is a JSON file that describes a binary frame. The phone builds frames in that exact layout and sends them to a board over USB or Bluetooth LE. Use one when the board **already has its own protocol** and you don't want to change it: no AllSense library on the board, no handshake.

- Examples ship in the app and in the protocol repository's [`templates/`](https://github.com/wen-da-ng/otterbridge-allsense-protocol/tree/main/templates) folder (e.g. `my_robot_imu.json`).
- Import your own in the app: **Home → Connect → Microcontroller**, on the USB board: **Speaks → Change → Import template…**
- Pick a template per board in the same place. The choice is remembered by the board's USB vendor and product ID.
- **Bluetooth LE boards** with their own protocol show under **Connect → Microcontroller → By Bluetooth** as "Nearby · its own protocol". Tap **Connect…** and pick the template. The choice is remembered by the board's Bluetooth address; change it under **Speaks**, or **Forget** the board.
- Licence: the format is part of the protocol spec (MIT).

## Example

```json
{
  "name": "my_robot_imu",
  "description": "Accelerometer and gyroscope as 16-bit integers.",
  "header": "AA 55",
  "rate_hz": 100,
  "fields": [
    {"src": "accelerometer", "idx": [0, 1, 2], "type": "i16", "scale": 100},
    {"src": "gyroscope", "idx": [0, 1, 2], "type": "i16", "scale": 1000},
    {"type": "seq_u8"}
  ],
  "checksum": "xor8"
}
```

That gives 16-byte frames, 100 per second:

| Bytes | 0–1 | 2–7 | 8–13 | 14 | 15 |
|---|---|---|---|---|---|
| Content | `AA 55` | accel x, y, z (int16, m/s² × 100) | gyro x, y, z (int16, rad/s × 1000) | counter | XOR of bytes 2–14 |

9.81 m/s² goes out as 981 (`D5 03`, little-endian).

## Keys

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | a–z, 0–9 and `_`, starting with a letter. Shown in the app. |
| `description` | no | One line, shown in the app. |
| `rate_hz` | yes | Frames per second, up to 1000. The sensors run at this rate too. |
| `header` | no | Hex bytes at the start of every frame: `"AA 55"`, `"aa55"` or `"0xAA 0x55"`. |
| `fields` | yes | The frame's contents after the header, in order (below). |
| `checksum` | no | `none` (default), `xor8`, `sum8` (low byte of the sum), `crc8` (poly 0x07, init 0; `"123456789"` → `0xF4`), `crc16_ccitt` (CCITT-FALSE: poly 0x1021, init 0xFFFF; `"123456789"` → `0x29B1`, written in the template's `endian`). |
| `checksum_covers` | no | `after_header` (default) or `all` (header included). The checksum is always last. |
| `endian` | no | `little` (default) or `big`, for every multi-byte number including a 2-byte checksum. |
| `baud` | no | Serial speed for boards with a USB-UART chip (CH340, CP210x…). Default 115200. Native-USB boards ignore it. |
| `ble` | no | For a BLE board with an unusual serial service: `{"service": "<uuid>", "characteristic": "<uuid>"}` to write frames to. 16-bit UUIDs like `"FFE1"` work. Without it, the phone uses the Nordic UART Service (writes to `6e400002-…`) or the HM-10 style `FFE0` service (writes to `FFE1`). |

### Fields

| Field | Example | Meaning |
|---|---|---|
| value | `{"src": "accelerometer", "idx": [0, 1, 2], "type": "i16", "scale": 100, "offset": 0}` | Values `idx` of stream `src`, each written as `value × scale + offset` in `type`. `src` is the stream's name in the app, its full topic, or its stable ID. `idx` defaults to `[0]`; a single number also works. |
| counter | `{"type": "seq_u8"}` (or `seq_u16`, `seq_u32`) | Goes up by one per frame and wraps. |
| constant | `{"type": "const", "bytes": "0D 0A"}` | Fixed bytes anywhere in the frame (a type code, a footer). |

Types: `u8`, `i8`, `u16`, `i16`, `u32`, `i32` and `f32` (IEEE-754 float).
- `scale` and `offset` can be any real number and apply to every type, `f32` included. Unit conversions are just a scale: rad/s → 0.01 °/s is `"scale": 5729.578` (100 × 180/π); a negative scale flips an axis.
- Integers are rounded half up (`floor(x + 0.5)`: 2.5 → 3, −2.5 → −2), then clamped to the type's range (300 in a `u8` is 255).
- A missing value, or NaN, is written as 0 before scaling.
- Not supported (yet): 24-bit and 64-bit numbers, bit fields, text or variable-length frames.

## Stream names and units

`src` is the stream's name as the app shows it under Sensors. If you rename a stream, use the new name, or put its stable ID in `src` (Advanced mode shows it), which never changes. Default names come from Android's sensor type; a second sensor of the same type gets `_2`, and wake-up copies end in `_wakeup`. The common ones:

| `src` (default name) | Values (`idx` 0, 1, 2…) | Unit |
|---|---|---|
| `accelerometer` | x, y, z (includes gravity) | m/s² |
| `linear_acceleration` | x, y, z (gravity removed) | m/s² |
| `gravity` | x, y, z | m/s² |
| `gyroscope` | x, y, z (drift-corrected) | rad/s |
| `gyroscope_uncalibrated` | x, y, z, then drift x, y, z | rad/s |
| `magnetic_field` | x, y, z | µT |
| `game_rotation_vector` | x·sin(θ/2), y·sin(θ/2), z·sin(θ/2), cos(θ/2) (quaternion, no magnetometer) | — |
| `rotation_vector` | same as above, then heading accuracy | — (accuracy in rad) |
| `pressure` | pressure | hPa |
| `light` | illuminance | lx |
| `proximity` | distance | cm |
| `step_counter` | steps since boot | — |
| `position` | latitude, longitude, altitude, accuracy, speed, bearing, vertical accuracy | °, °, m, m, m/s, °, m |
| `satellites` | visible, used in fix, mean C/N0 used, best C/N0 | —, —, dB-Hz, dB-Hz |
| `battery` | level, voltage, temperature, current, charging (1/0) | %, V, °C, mA, — |
| `wifi_signal` | RSSI, link speed, frequency | dBm, Mbps, MHz |
| `cell_signal` | strength, level | dBm, 0–4 |

`gyroscope`, not `gyroscope_uncalibrated`, is what a balancing robot usually wants. GNSS streams need the app's location access and Location on; until the first fix, no frames go out.

**GPS coordinates:** templates get full double precision, so send latitude and longitude as `i32` with `"scale": 10000000` (degrees × 10⁷, the usual format in drone and GPS-module protocols). As `f32` they'd lose about a metre. The full list for your phone, with exact names: the app's Sensors pages, or `allsense list "<link>"` with the Python client.

**Axes** are Android's: with the phone flat and its screen up, x points right, y towards the top of the screen, z up out of the screen. If the phone is mounted differently, pick the matching index for each of your robot's axes (`"idx": [1, 0, 2]` swaps x and y) and flip with a negative scale.

## Connecting the board

- **Board with USB** (ESP32, Arduino, Pico, or a dev board with a CH340/CP210x/FTDI chip): a USB cable to the phone's port (USB-C to USB-C, or an OTG adapter).
- **Bare UART** (a motor controller with TX/RX pins only): put a USB-UART adapter (CH340, CP210x, FTDI or PL2303) between the phone and the board. Wire the adapter's TX to the board's RX (the phone only sends; RX is optional) and GND to GND. Match the logic level: 3.3 V boards need a 3.3 V adapter. Set `baud` to the board's speed.

### Over Bluetooth LE

- The phone finds boards that advertise the Nordic UART Service (`6e400001-b5a3-f393-e0a9-e50e24dcca9e`), the HM-10 / HC-08 / JDY style `FFE0` service, or a service a template names.
- Frames are written to the write characteristic, without response when the board allows it. BLE splits and joins writes freely, so the board must read the incoming bytes as a stream and find frames by their header, like a UART.
- The phone asks for a 247-byte MTU; with older modules (HM-10: 20-byte packets) a frame simply spans several packets.
- Throughput is lower than USB: plan for about 1–5 KB/s on cheap modules (the link test doesn't run on template boards; check `rate_hz × frame size`).
- The phone ignores anything the board notifies back.

## How the phone sends them

- Every 1/`rate_hz` s the phone builds one frame from the **newest** sample of each stream. Streams that update more slowly repeat their last value.
- No frames go out until every stream in the template has delivered a sample, or while one of them isn't shared over USB (**Connect → Microcontroller → Streams it may send**).
- Whatever the board sends back is ignored, so the board can print debug text on the same cable.
- If a name in `src` matches no stream, the app shows it as "no stream with this name" and nothing is sent.
- The sensors run at the frame rate (the app asks Android for 2× that and spaces samples out), and frames go out on a steady timer. Each frame carries the newest sample, which is at most one sample period old.
- If the cable comes out, the phone reconnects and resumes when it's plugged back in, while streaming is on. The board needs no logic for this; it just sees frames stop and start.

## Testing a template without the phone

1. **Check the file** with the app's own parser (from the repo root; relative paths are from there, absolute Windows paths like `C:\path\t.json` also work):
   ```
   ./gradlew -q :core:model:checkTemplate --args="my_template.json"
   ```
   It prints the settings (endian, checksum, baud), the data rate, and an example frame with a map of what every byte is, or says exactly what's wrong.
2. **Check the board** (USB serial on a PC): `allsense-fake-template --port COM3 --template my_template.json` sends frames like the phone does, with typical values (gravity on z, 1013 hPa…). If the board prints `frames=<good> bad=<bad>` once a second (like the TemplateReader example), the tool checks the counts and says PASS or FAIL. If it can't print, the tool says "SENT, not verified": then check the board's own behaviour (motors, LEDs, its debug port).
   Over BLE: `allsense-fake-template --ble "<board name>" --template my_template.json` (the board must not be connected to the phone). The TemplateReaderBLE example reports its counts as notifications, so the tool can check it.
3. Decode a captured frame: `allsense-template decode my_template.json "AA 55 0C 00 …"`.

`allsense_testkit.template` (in the `allsense-testkit` package, `pip install allsense-testkit`) is a second, separate implementation in Python. Both it and the app must produce the bytes in `vectors/template_vectors.json`, and the unit tests check that.

## Limits (version 0)

- Bluetooth Classic (SPP, HC-05) isn't supported.
- Sensor streams only, like the rest of protocol v0.
- Frames are at most 1024 bytes.
