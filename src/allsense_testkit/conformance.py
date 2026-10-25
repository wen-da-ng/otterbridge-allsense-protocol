"""Runs a client in any language through the same scenarios against the fake phone.

    allsense-conformance -- <program> [args…]

The program is called once per scenario as ``<program> [args…] <link> <scenario>``. It prints what it
likes, and these lines:

- ``WAIT <action>``: it's ready for the driver to do something to the phone (``share heart_rate``,
  ``restart``, ``freeze``, ``ping``). The driver does it, then writes ``GO`` (or ``GO <result>``) to
  its stdin.
- ``PASS``: the scenario passed. Anything else (a non-zero exit, a timeout, no PASS) fails it.

Scenarios (each client implements all of them; see the C++ client's tests/conformance.cpp and the Rust
client's examples/conformance.rs):

- ``unit``: offline checks (link parsing, a link without a token).
- ``basics``: connect, catalog, find (with a "did you mean"), samples, latest/read, rates, several
  streams, a callback, refused and not-shared states, null values, commands, clock sync, snapshot.
- ``share``: subscribes to heart_rate (not shared), WAIT share heart_rate, then gets its samples.
- ``reconnect``: gets samples, WAIT restart (the phone goes away for a second), gets samples again.
- ``stall``: gets samples, WAIT freeze (the phone goes silent for 8 s without closing anything),
  reconnects by itself (the stall watchdog) and gets samples again.
- ``ping``: WAIT ping (the app's link test); GO <ms> if the client answered.
- ``token``: connecting with a wrong token fails with the client's token error, quickly.

Also runs the quickstart and print_values examples with ``--example`` (their output must show 9.81,
the fake phone's z axis).
"""

from __future__ import annotations

import argparse
import logging
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from .fake_phone import FakePhone

SCENARIOS = ["unit", "basics", "share", "reconnect", "stall", "ping", "token"]


def _program(cmd):
    """Windows can't start a relative path with forward slashes: make the program's path absolute."""
    exe = Path(cmd[0])
    return [str(exe.resolve())] + cmd[1:] if exe.exists() else cmd


def _reader(stream, q):
    for line in iter(stream.readline, ""):
        q.put(line.rstrip("\r\n"))
    q.put(None)


def _act(phone: FakePhone, action: str) -> str:
    if action.startswith("share "):
        phone.set_shared(action.split(" ", 1)[1], True)
    elif action == "restart":
        phone.stop()
        time.sleep(1.0)
        phone.restart()
    elif action == "freeze":
        phone.frozen.set()
        threading.Timer(8.0, phone.frozen.clear).start()
    elif action == "ping":
        rtts = phone.ping(timeout=2.0)
        return f" {rtts[0]:.1f}" if rtts and rtts[0] is not None else " none"
    else:
        raise ValueError(f"unknown action {action!r}")
    return ""


def run_scenario(cmd, scenario, timeout, verbose):
    phone = FakePhone()
    url = phone.url
    if scenario == "token":
        url = url.replace("testtoken", "wrongtoken")
    p = subprocess.Popen(cmd + [url, scenario], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    q: queue.Queue = queue.Queue()
    threading.Thread(target=_reader, args=(p.stdout, q), daemon=True).start()
    out, passed, deadline = [], False, time.monotonic() + timeout
    try:
        while True:
            try:
                line = q.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                out.append(f"(timed out after {timeout} s)")
                break
            if line is None:
                break
            out.append(line)
            if verbose:
                print("   |", line)
            if line.startswith("WAIT "):
                result = _act(phone, line[5:].strip())
                p.stdin.write("GO" + result + "\n")
                p.stdin.flush()
            elif line.strip() == "PASS":
                passed = True
        code = p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        code = None
    finally:
        if p.poll() is None:
            p.kill()
        phone.stop()
    return passed and code == 0, out, code


def run_example(cmd, name, verbose):
    phone = FakePhone()
    p = subprocess.Popen(cmd + [phone.url], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    q: queue.Queue = queue.Queue()
    threading.Thread(target=_reader, args=(p.stdout, q), daemon=True).start()
    lines = []
    try:
        while len(lines) < 5:
            line = q.get(timeout=15)
            if line is None:
                break
            lines.append(line)
            if verbose:
                print("   |", line)
    except queue.Empty:
        lines.append("(timed out)")
    finally:
        p.kill()
        phone.stop()
    return len(lines) >= 5 and "9.81" in "\n".join(lines), lines


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Clients that exit without a close frame are fine here; keep the fake phone's server quiet about it.
    logging.getLogger("websockets").setLevel(logging.CRITICAL)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", choices=SCENARIOS, help="run just these scenarios")
    ap.add_argument("--example", action="append", default=[], metavar="CMD",
                    help="an example program to run with the link (quoted, may repeat)")
    ap.add_argument("--timeout", type=float, default=45)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="-- <program> [args…]")
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    cmd = _program(cmd) if cmd else cmd
    if not cmd and not a.example:
        ap.error("give a program after --, or --example")

    failed = 0
    for scenario in (a.only or SCENARIOS) if cmd else []:
        start = time.monotonic()
        ok, out, code = run_scenario(cmd, scenario, a.timeout, a.verbose)
        print(f"{'ok  ' if ok else 'FAIL'} {scenario:<10} {time.monotonic() - start:5.1f} s")
        if not ok:
            failed += 1
            print("\n".join("     " + line for line in out[-30:]) + f"\n     (exit code {code})")
    for example in a.example:
        ok, lines = run_example(_program(example.split()), example, a.verbose)
        print(f"{'ok  ' if ok else 'FAIL'} example {Path(example.split()[0]).name}")
        if not ok:
            failed += 1
            print("\n".join("     " + line for line in lines))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
