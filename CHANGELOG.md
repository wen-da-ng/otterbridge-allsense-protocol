# Changelog

## 0.1.0 (unreleased)

- Protocol version 0: JSON over WebSocket, video and audio over HTTP, the compact protocol over USB and BLE, frame templates, recordings, MQTT.
- `allsense-testkit`: WebSocket, USB serial, BLE and frame-template fake phones; compact and template codecs (`allsense-template check` prints a byte map of an example frame); the conformance runner.
- The fake phone sends `subscribed` before a stream's first sample, so a quick sharing change can't be undone by a late `subscribed`.
- Shared vectors: `vectors/compact_vectors.json`, `vectors/template_vectors.json`.
