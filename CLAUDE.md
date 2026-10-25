# CLAUDE.md

The AllSense protocol (`spec/`), its shared vectors (`vectors/`), example frame templates (`templates/`) and the `allsense-testkit` Python package (`src/allsense_testkit/`: fake phones, compact and template codecs, the conformance runner). Public, MIT.

## Working here

- **The user makes every commit and push.** Edit files and run the tests, then hand over: what changed, the test results, and a one-line commit message suggestion. Never run `git commit`, `git push`, tags or releases; add no Co-Authored-By line unless asked.
- **Public repository:** never write the user's serials, IPs, Wi-Fi details, home location, tokens or file paths into it. Machine facts go in `CLAUDE.local.md` (git-ignored).

## Test

```bash
.venv/Scripts/python -m pytest          # vectors, the fake phone, the conformance runner
.venv/Scripts/python -m allsense_testkit.compact   # codec self-test
```

Setup: `python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"`.

## How it fits

- The app (private) and the clients (`otterbridge-allsense-python`, `-cpp`, `-rust`, `-ros2`, `-arduino`) test against this package. The docs site (`otterbridge-allsense-docs`) publishes `spec/` from here.
- **A protocol change lands here first**, in one change: spec, vectors (regenerate with `tools/gen_compact_vectors.py` and `tools/gen_template_vectors.py`), fake phone, and a conformance scenario. Then a test kit release; the app and clients move to it.
- Specs link to each other relatively (`[PROTOCOL.md](PROTOCOL.md)`), so they work on GitHub and on the docs site; links elsewhere are absolute (`https://docs.allsense.otterbridge.org/...`).
