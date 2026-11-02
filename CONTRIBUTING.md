# Contributing

Read [AGENTS.md](AGENTS.md) before changing scheduling or execution. Use an Apple Silicon Mac for native UI work (macOS 14+), or Linux for the experimental headless worker. See [Linux setup](docs/LINUX.md). Graph/MCP tools are optional. No account, GPU model, or cloud service is required to develop the queue.

## Setup and checks

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export H3_QUEUE_PYTHON="$PWD/.venv/bin/python"
.venv/bin/python -m unittest discover -s tests -v
DEVELOPER_DIR=/Library/Developer/CommandLineTools ./scripts/build-app.sh
.venv/bin/python scripts/check-public.py
```

The full Python suite requires FFmpeg/ffprobe with H.264/AAC support. The provider suite can run without them: `-m unittest discover -s tests -p 'test_providers.py' -v`. Tests use temporary databases, simulated telemetry, fake model programs, tiny WAVs, and tiny generated video fixtures. They must not start actual H3/TTS, alter production mode, create system resource pressure, or download weights.

Native system-metric checks:

```sh
mkdir -p .build
DEVELOPER_DIR=/Library/Developer/CommandLineTools xcrun swiftc -parse-as-library -module-cache-path .build/module-cache macos/SystemUsage.swift tests/SystemUsageTests.swift -o .build/system-usage-tests
.build/system-usage-tests
./scripts/test-localization.sh
codesign --verify --deep --strict 'dist/H3 Queue.app'
```

The GitHub workflow performs native checks on macOS and Python fake-runtime checks on Linux x86-64/ARM64. It does not execute a real model, access a deployment, publish releases, or upload user state. A local build uses ad-hoc signing, not notarization.

See [the recorded source-preparation validation](docs/VALIDATION.md) for the checks actually run and their limits.

## Making a change

Keep queue policy independent from model names. Prefer a registered command provider for an external executable; add a Python adapter when specialized normalization or validation justifies it. Keep inputs as JSON and subprocess invocation as argv arrays. Document behavior in the matching user/agent guide and add meaningful tests for affected ownership, cancellation, provenance, or migration paths.

Preserve existing data and execution mode. Never use production `.state` as a test fixture. New attempts must not overwrite old evidence. Run required checks once; expand testing when failures or changed behavior justify it.

For UI previews, the generated app's `config.json` may point `preview` at an isolated status JSON fixture. Preview mode refuses queue writes; remove that field for normal use. Refresh only the exact app executable when needed; do not restart model wrappers or workers for a visual change.

All UI text belongs in every `macos/Resources/*.lproj/Localizable.strings` catalog (currently 11 languages). Follow the [localization guide](docs/LOCALIZATION.md) for keys, format arguments, language switching, and isolated checks. Preserve user/provider text and machine-readable protocol values.

## Pull requests and issues

Describe the user-visible problem, resulting behavior, relevant validation, and remaining limitations. Include a small sanitized reproduction, OS/architecture, Python version, provider/runtime identity, and redacted error information. Never attach a full `.state`, user media, model weights, or raw private logs. See [SECURITY.md](SECURITY.md) for sensitive reports.

Before committing, run `scripts/check-public.py` and inspect the diff yourself. Its checks cover local links, example JSON, selected private path/key patterns, and accidental binary/state files; it is not a complete secret scanner. By contributing code/docs, you agree to make your contribution available under this project's [MIT license](LICENSE). External models/dependencies keep their own licenses.

For a reviewed local source snapshot, use `python3 scripts/export-source.py`; see [source packaging](docs/RELEASING.md#source-packaging). This exports only checked source candidates and never publishes or includes local Git history.
