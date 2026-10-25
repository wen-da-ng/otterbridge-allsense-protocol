---
description: "Save streams to files on the phone, with the screen off, then get them as CSV, or as MCAP for Foxglove and ROS 2."
---

# Recordings

Log a run on the phone itself, then take the files home.
{ .lead }

!!! robot "For example"
    Strap the phone to a rover, record IMU and GPS for a test drive with no laptop along, then open the run in Foxglove.

The app can save streams to files on the phone: **Robot → Recording**. Choose the streams and a rate, then **Record**. Streaming doesn't have to be on: a phone strapped to a robot can log a run on its own, with the screen off. The notification shows it ("AllSense is recording"); its **Stop** ends streaming and recording. Starting or stopping streaming doesn't touch a recording in progress.

With streaming off nothing listens on the network, so `/recordings` (below) works only while streaming is on. If Android kills the app, a recording ends with what was written (at most the last second is lost) and isn't restarted.

## Getting the files

- **Share** in the Recording card: a .zip to Drive, email, a messaging app…
- **From a computer** on the same network: the link from **Connect → Browser** with `/recordings` instead of `/` (same token), e.g. `http://192.168.1.20:8765/recordings?token=…`. It lists the recordings; each downloads as a .zip.
- **Over a USB cable** (file transfer mode): `Android/data/io.github.wen_da_ng.otterbridge.allsense/files/recordings/`.

## Format (version 1)

One folder (or .zip containing it) per recording, named `allsense_<device>_<yyyyMMdd-HHmmss>` (the phone's local start time):

```
allsense_phone_20261017-191502/
  meta.json
  accelerometer.csv
  position.csv
```

**One CSV per stream**, named after the stream (its name in the app):

```
t_ns,time_unix,x (m/s²),y (m/s²),z (m/s²)
1234567890123,1760700000.123456,0.12,9.79,0.33
```

- `t_ns`: the sample's timestamp in nanoseconds on the phone's boot clock, the same clock as the protocol's `t`. Use it for intervals and rates.
- `time_unix`: the same moment in Unix seconds (6 decimals), from `t_ns + boot_to_unix_ns`.
- Then one column per field, with its unit in brackets. Empty cell = missing value (NaN): no GNSS fix, bearing while standing still, Wi-Fi not connected.
- Values are written in full precision (GNSS latitude/longitude as doubles).
- Continuous streams have one row per sample at the chosen rate; event streams (GNSS, light, proximity…) one per event.
- The files are flushed every second, so a crash or a dead battery loses at most the last second (the last line may be cut short; readers skip it).

**`meta.json`**:

```json
{
  "format": "allsense-recording", "version": 1, "app_version": "0.1.0",
  "device": "phone", "started_unix": 1760700000.1, "boot_to_unix_ns": 1760690000000000000,
  "streams": [
    {"name": "accelerometer", "file": "accelerometer.csv", "topic": "allsense.phone.sensors.accelerometer",
     "id": "sensors/1/…", "category": "sensors", "type": "Accelerometer", "stream_type": "android.sensor.accelerometer",
     "fields": ["x", "y", "z"], "units": ["m/s²", "m/s²", "m/s²"], "reporting": "continuous", "rate_hz": 50, "hardware": "…"}
  ]
}
```

The stream entries use the same keys as the protocol's catalog ([PROTOCOL.md](PROTOCOL.md)).

## Foxglove and ROS 2 (MCAP)

[MCAP](https://mcap.dev) is the log format Foxglove and ROS 2 bags open directly. Convert a recording on the computer:

```bash
pip install "allsense[mcap]"
allsense mcap allsense_phone_20261017-191502.zip              # → allsense_phone_20261017-191502.mcap, for Foxglove
allsense mcap allsense_phone_20261017-191502.zip --ros2       # → …_ros2.mcap: ros2 bag info / play
```

In Python: `allsense.export_mcap("…zip", "out.mcap", profile="foxglove" or "ros2")`.

- Topics are the ROS bridge's: `/allsense/<device>/<category>/<name>`, stamped with each sample's time (Unix, from `t_ns + boot_to_unix_ns`).
- **Foxglove** (default): JSON with the fields by name (`x`, `latitude`, `vertical_accuracy`; spaces become `_`); missing values are `null`. Plot `/allsense/phone/sensors/accelerometer.z`. GNSS position is also on `…/gnss/position/fix` as `foxglove.LocationFix`, so the Map panel draws the track.
- **ROS 2** (`--ros2`): the same standard messages as the bridge ([the bridge's README](https://github.com/wen-da-ng/otterbridge-allsense-ros2)): `sensor_msgs/Imu`, `NavSatFix`, `BatteryState`, `MagneticField`…, anything else `std_msgs/Float64MultiArray`. Play it with `ros2 bag play file_ros2.mcap` (Humble needs `ros-humble-rosbag2-storage-mcap` and `-s mcap`).

## Reading it

- **Python**: `pip install allsense`, then
  ```python
  rec = allsense.load_recording("allsense_phone_20261017-191502.zip")   # or the folder
  acc = rec["accelerometer"]
  times, values = acc.arrays()          # NumPy, Unix seconds and (n, 3) with NaN for missing
  lat = rec["position"].column("latitude")
  ```
- **Anything else** (Excel, pandas, MATLAB, R): they're plain CSV files with a header row.

Licence: this format description is MIT, like the protocol spec.
