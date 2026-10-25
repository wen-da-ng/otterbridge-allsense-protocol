"""A stand-in test program for the conformance runner's own tests. It doesn't speak the protocol; it
follows the runner's rules: print WAIT lines, read GO, print PASS (or fail when asked to).

    scripted_client.py <link> <scenario> [--fail]
    scripted_client.py --example <link>       prints five lines with the fake phone's z axis
"""
import sys

args = [a for a in sys.argv[1:] if not a.startswith("--")]
if "--example" in sys.argv:
    for _ in range(5):
        print("0.000 1.000 9.810", flush=True)
    sys.exit(0)

link, scenario = args
if "--fail" in sys.argv:
    print("deliberate failure", flush=True)
    sys.exit(1)
assert link.startswith("http://127.0.0.1:") and "token=" in link, link
wait = {"share": "share heart_rate", "reconnect": "restart", "stall": "freeze", "ping": "ping"}.get(scenario)
if wait:
    print(f"WAIT {wait}", flush=True)
    answer = sys.stdin.readline().strip()
    assert answer.startswith("GO"), answer
print("PASS", flush=True)
