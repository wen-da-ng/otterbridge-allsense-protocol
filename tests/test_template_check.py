"""allsense-template check: a byte map of an example frame, FAIL with the reason for a broken file."""

import glob
import json

from allsense_testkit import template


def test_check_prints_a_byte_map(capsys):
    assert template.main(["check", *sorted(glob.glob("templates/*.json"))]) == 0
    out = capsys.readouterr().out
    assert 'OK   my_robot_imu.json: "my_robot_imu", 16-byte frames at 100 Hz = 1600 B/s' in out
    assert "AA 55 64 00 C8 00 2C 01 E8 03 D0 07 B8 0B 00 0E" in out
    assert "bytes 15      0E           checksum (xor8)" in out


def test_check_fails_with_the_reason(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"name": "x", "fields": []}))
    assert template.main(["check", str(bad)]) == 1
    assert 'missing "rate_hz"' in capsys.readouterr().out
