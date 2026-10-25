# AllSense protocol

The wire formats of **AllSense by OtterBridge**, plus a test kit to check that a client speaks them correctly, without a phone.

[AllSense](https://github.com/wen-da-ng/otterbridge-allsense) turns an Android phone into a sensor hub for robots. Its app streams the phone's sensors, cameras and microphones to clients: a browser, Python, C++, Rust, ROS 2, Arduino boards or MQTT. This repository defines how they talk, so anyone can write another client.

| | |
|---|---|
| [spec/PROTOCOL.md](spec/PROTOCOL.md) | JSON over WebSocket, video and audio over HTTP, and the compact binary protocol over USB and Bluetooth LE |
| [spec/TEMPLATES.md](spec/TEMPLATES.md) | Frame templates: boards with their own binary format |
| [spec/RECORDING.md](spec/RECORDING.md) | The files the app records |
| [spec/MQTT.md](spec/MQTT.md) | Topics and messages over MQTT |
| [vectors/](vectors) | Byte-exact test vectors every implementation must reproduce |
| [templates/](templates) | Example frame templates |

The protocol is at **version 0**: experimental, and it may still change. Compatibility starts with version 1.

## The test kit

`allsense-testkit` is a Python package with stand-in phones and the shared test scenarios.

```bash
pip install allsense-testkit           # WebSocket fake phone + conformance runner
pip install "allsense-testkit[all]"    # + USB serial and BLE fake phones
```

| Command | Does |
|---|---|
| `allsense-fake-phone` | A stand-in phone on this computer, with a link like the app's. Point any client at it |
| `allsense-conformance -- <your test program>` | Runs your client through the shared scenarios (catalog, samples, sharing, reconnect, silent link, link test, wrong token) |
| `allsense-fake-serial --port COM3` | A stand-in phone for a board on a USB serial port (compact protocol) |
| `allsense-fake-ble` | A stand-in phone that connects to a BLE board |
| `allsense-fake-template --port COM3 --template t.json` | Sends frame-template frames, as the phone would |
| `allsense-template check t.json` / `decode t.json "AA 55 …"` | Checks a template and prints a byte map of an example frame; decodes a captured frame |

In Python tests:

```python
from allsense_testkit import FakePhone

phone = FakePhone()          # a fake phone on a free local port
client = connect(phone.url)  # your client, with the phone's link
phone.set_shared("accelerometer", False)   # act like the user in the app
phone.stop()
```

### Conformance

Your test program is called once per scenario as `<program> <link> <scenario>`. It prints `PASS` when the scenario passed, and `WAIT <action>` when the runner should do something to the phone (share a stream, restart, go silent, run a link test); the runner answers on stdin with `GO`. The scenarios and the exact rules are in [src/allsense_testkit/conformance.py](src/allsense_testkit/conformance.py). The C++ and Rust clients are examples of test programs.

```bash
allsense-conformance --example ./build/quickstart -- ./build/conformance
```

## Implementations

| | Repository | Install |
|---|---|---|
| Android app | [otterbridge-allsense](https://github.com/wen-da-ng/otterbridge-allsense) | APK in Releases |
| Python | [otterbridge-allsense-python](https://github.com/wen-da-ng/otterbridge-allsense-python) | `pip install allsense` |
| C++ | [otterbridge-allsense-cpp](https://github.com/wen-da-ng/otterbridge-allsense-cpp) | CMake FetchContent |
| Rust | [otterbridge-allsense-rust](https://github.com/wen-da-ng/otterbridge-allsense-rust) | `cargo add allsense` |
| ROS 2 | [otterbridge-allsense-ros2](https://github.com/wen-da-ng/otterbridge-allsense-ros2) | ROS index |
| Arduino / ESP32 | [otterbridge-allsense-arduino](https://github.com/wen-da-ng/otterbridge-allsense-arduino) | Arduino Library Manager |

Docs: [docs.allsense.otterbridge.org](https://docs.allsense.otterbridge.org/)

## Changing the protocol

A change lands here first, all in one pull request: the spec, the vectors (regenerate them with `python tools/gen_compact_vectors.py` and `python tools/gen_template_vectors.py`), the fake phone, and a conformance scenario. A new test kit release follows; the app and every client then move to it, and their CI shows what needs updating.

## Development

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"     # Windows; .venv/bin/pip elsewhere
.venv/Scripts/python -m pytest
```

## License

MIT. Anyone may implement the protocol, in any project.
