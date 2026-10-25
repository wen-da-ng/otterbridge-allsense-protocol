"""The conformance runner: runs a test program per scenario, answers its WAIT lines, reports PASS/FAIL."""

import subprocess
import sys
from pathlib import Path

RUNNER = [sys.executable, "-m", "allsense_testkit.conformance"]
CLIENT = str(Path(__file__).with_name("scripted_client.py"))


def run(*args):
    r = subprocess.run([*RUNNER, *args], capture_output=True, text=True, encoding="utf-8", timeout=120)
    return r.returncode, r.stdout


def test_passing_client():
    code, out = run("--only", "unit", "share", "ping", "--", sys.executable, CLIENT)
    assert code == 0, out
    assert out.count("ok  ") == 3


def test_failing_client_is_reported():
    code, out = run("--only", "unit", "--", sys.executable, CLIENT, "--fail")
    assert code == 1
    assert "FAIL unit" in out and "deliberate failure" in out


def test_examples_must_show_the_fake_values():
    code, out = run("--example", f"{sys.executable} {CLIENT} --example")
    assert code == 0, out
    assert "ok   example" in out
