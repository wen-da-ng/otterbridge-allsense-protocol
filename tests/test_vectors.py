"""The shared vectors match the reference codecs, and the example templates load."""

import json
from pathlib import Path

import pytest

from allsense_testkit import compact as ac
from allsense_testkit.template import Template

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return json.loads((ROOT / "vectors" / name).read_text(encoding="utf-8"))


def test_compact_vectors():
    v = load("compact_vectors.json")
    for c in v["crc16"]:
        assert ac.crc16(c["data_ascii"].encode()) == int(c["crc"], 16)
    for c in v["cobs"]:
        assert ac.cobs_encode(bytes.fromhex(c["raw"])).hex() == c["encoded"]
        assert ac.cobs_decode(bytes.fromhex(c["encoded"])).hex() == c["raw"]
    for f in v["frames"]:
        assert ac.frame(bytes.fromhex(f["payload"])).hex() == f["frame"], f["what"]


def test_compact_reader_resyncs_after_noise():
    r = ac.Reader()
    frames = r.feed(b"\x41\x42\x00" + ac.frame(ac.hello("x")))
    assert frames == [ac.hello("x")] and r.corrupt == 1


def test_template_vectors():
    for c in load("template_vectors.json")["cases"]:
        assert Template(c["template"]).encode(c["values"], c["seq"]).hex() == c["hex"], c["template"]["name"]


@pytest.mark.parametrize("path", sorted((ROOT / "templates").glob("*.json")), ids=lambda p: p.name)
def test_example_templates_load(path):
    t = Template.load(str(path))
    assert t.size > 0 and t.rate_hz > 0 and t.sources
