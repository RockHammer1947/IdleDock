# Install and first run

[中文概览](../README.zh-CN.md) · [Deployment contract](DEPLOYMENT.md) · [Usage](USAGE.md)

## Requirements

| Component | Needed for |
| --- | --- |
| Apple Silicon Mac, macOS 14+ | Supported application/runtime target; Intel/Linux/Windows are not supported releases |
| Python 3.10+ | Queue; use a dedicated virtual environment |
| `psutil` from `requirements.txt` | Process ownership and resource protection |
| Apple Command Line Tools | Compiling the SwiftUI/AppKit app |
| macmon with JSON `pipe` output | Temperature and power monitoring before execution |
| FFmpeg and ffprobe | Video generation/validation and the complete test suite |
| Local model runtime and weights | Only the providers you intend to use |

The queue does not install models or system packages. If you use Homebrew, `brew install python@3.12 ffmpeg macmon` supplies these host tools; select that Python when creating the venv. Otherwise install the tools using their upstream instructions. macmon's upstream documents its Homebrew installation and JSON pipe interface: [macmon](https://github.com/vladkens/macmon#readme). Python process monitoring is installed in the venv: [psutil installation](https://psutil.io/install/).

Default execution protection reserves 15 GiB of free disk and 4 GiB of available memory, in addition to whatever a provider needs. These are admission thresholds, not a promise that a particular model will fit. Missing/stale temperature readings block starts; do not disable that guard to finish installation.

## Prepare the queue environment

Clone the source and enter its root:

```sh
git clone https://github.com/RockHammer1947/IdleDock.git
cd IdleDock
```

Check `python3 --version` is at least 3.10, then:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export H3_QUEUE_PYTHON="$PWD/.venv/bin/python"
./queue --help
.venv/bin/python -m unittest discover -s tests -p 'test_providers.py' -v
```

No real inference is used by these tests. Each test creates its own temporary deployment/state and lightweight outputs. The complete suite also needs FFmpeg/ffprobe; see [CONTRIBUTING.md](../CONTRIBUTING.md).

Interpreter selection is: explicit `H3_QUEUE_PYTHON` → saved `.state/python-path` → checkout `.venv/bin/python` → legacy deployment Python if present → `python3` on PATH. An invalid explicit/saved path fails instead of silently choosing another interpreter. `setup.command` saves the selected absolute interpreter. Use `H3_QUEUE_PYTHON` again when intentionally changing it.

## Isolated demo

This example imports a CPU-only JSON echo task into a separate queue. It does not affect an existing `.state` queue. Run it in a separate terminal so the environment variables remain scoped to the demo:

```sh
export H3_QUEUE_PYTHON="$PWD/.venv/bin/python"
.venv/bin/python scripts/prepare-demo.py .local/first-demo
export H3_QUEUE_HOME="$PWD/.local/first-demo/state"
./queue configure --deployment "$PWD/.local/first-demo/deployment"
./queue register-provider "$PWD/.local/first-demo/provider.json"
./queue enqueue "$PWD/.local/first-demo/request.json" --title 'First local job'
./queue status
./queue doctor
```

Expected: `mode` is `paused`, one queued job, no active attempt. `prepare-demo.py` refuses to overwrite an existing destination. To repeat, choose a different destination and update the paths consistently. The example session has no resident model service to manage; never copy it over a production H3/Qwen deployment.

The enqueue command starts a background worker and sensor sampler, but does not enable computation. To run this lightweight example when **you choose to**, wait for fresh telemetry and execute `./queue start`. The completed result is a small JSON file under the demo state's `runs/`. `./queue pause` leaves it idle afterward. No model is loaded by the example. Do not run `setup.command` from the demo terminal: the GUI is intended for the main queue.

## Connect a deployment

In your normal terminal, with the intended queue home, configure the external deployment **before starting a worker**:

```sh
./queue configure --deployment /absolute/local-model-deployment
./queue providers
./queue doctor
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for the session contract, standalone template, TTS profile schema, and H3 layout. `configure` checks for an `agent_session.py` file; it does not prove the implementation or a model is compatible. `providers` reports profiles/files, not successful generation. `doctor` reports paths and dependencies without running model code. Missing H3-only dependencies are expected for a command-only deployment.

Changing a deployment does not rewrite already queued jobs; each contains a snapshot of its deployment and dependencies. A running worker retains its original telemetry deployment path until restarted. Schedule configuration changes during a maintenance window with no active attempt; do not kill a wrapper to apply them.

## Build and open the app

```sh
./setup.command
```

This checks Python/psutil, saves the interpreter, compiles and ad-hoc signs `dist/H3 Queue.app`, initializes the database, starts a worker, and opens the app. A **new** database defaults to paused. Setup preserves an **existing** mode, so an enabled queue may continue executing while setup runs.

For build-only validation without starting a worker:

```sh
DEVELOPER_DIR=/Library/Developer/CommandLineTools ./scripts/build-app.sh
```

The app's configuration stores absolute checkout/Python paths. Keep the checkout in place; rebuild if you move it. Do not distribute the generated app as a portable or notarized release. For now distribute source and build locally. The generated app does not persist a custom queue home in its config. A normal Finder launch uses `.state`; use the CLI for predictable custom `H3_QUEUE_HOME` workflows.

Existing attempts and local services also contain absolute paths. When relocating an existing checkout, preserve an old-path filesystem symlink so historical outputs and services remain reachable. Rebuilding the UI does not rewrite queue history; do not edit the runtime database to rename paths. Keep the legacy app filename and bundle/service identifiers compatible.

## Tool discovery and background service

FFmpeg/ffprobe are discovered through explicit `H3_QUEUE_FFMPEG` / `H3_QUEUE_FFPROBE`, then PATH, `/opt/homebrew/bin`, `/usr/local/bin`, and the legacy `~/.homebrew/bin`. macmon uses `H3_QUEUE_MACMON`, then the configured deployment's `H3/tools/macmon/macmon`, followed by those search locations. Overrides must be absolute executable paths. An invalid override does not fall back.

Environment variables apply to processes launched from that environment. A Finder-launched GUI does not inherit terminal exports. Prefer standard tool locations, or install the worker's login service from the configured shell:

```sh
./queue launch-agent install
```

This saves tool overrides, PATH, and the queue home in `~/Library/LaunchAgents/local.queue-mac-h3.worker.plist`. It enables a login worker, not a compute mode. Existing active mode still applies. Removal is explicit: `./queue launch-agent remove` requests an immediate stop and unloads the login service. The fixed service label supports one login-managed queue per user.

## Troubleshooting

| Symptom | Next check |
| --- | --- |
| Python syntax/import error | Interpreter version, `H3_QUEUE_PYTHON`, and `pip install -r requirements.txt` in that environment |
| App cannot find checkout | Rebuild after moving source or Python; do not reuse another machine's app config |
| Swift reports duplicate modules after moving a checkout | Move aside the old `.build/module-cache` and rebuild from the canonical checkout path; cached modules can retain the previous absolute path |
| Temperature monitoring unavailable | `doctor.tools.macmon`, executable permissions, `status.telemetry.stale`, then `.state/worker.log`; hardware/macOS compatibility varies |
| Video decode fails / ffmpeg missing | `doctor.tools`, FFmpeg build with H.264/AAC support, attempt logs |
| Model/profile missing | Deployment contract and local runtime; the queue never downloads a fallback model |
| Waiting for compute resources | Another participant owns the deployment lock; wait or use the queue's stop/cancel action |
| Jobs do not run | Mode, schedule/timezone, idle requirement, safety latch, sensor freshness, disk/memory reserves |

To uninstall, explicitly stop work and wait for restoration, remove a configured login service, close the exact app, then remove source/app only when you want to. Keep `.state` until outputs and history are backed up. Do not use broad process-kill commands or remove a shared model deployment.
