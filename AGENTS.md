# IdleDock — agent instructions

This is a macOS local compute queue with an experimental Linux headless worker: Python + SQLite + psutil, native SwiftUI/AppKit UI. It schedules H3, batch TTS, and registered command providers. No web service, npm, Docker, or cloud account is needed. Model deployments are external.

Read [docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md) for operational recipes. If `AGENTS.local.md` exists, read it explicitly for this machine's deployment paths and current user restrictions; it is ignored by Git, not automatically loaded by every agent. Current user instructions take precedence over historical local notes.

## First actions

1. Work from the checkout root; use its absolute `queue` path from other directories.
2. Read `./queue status`, `./queue doctor`, and `./queue providers`. Summarize mode, counts, active task, reason, and telemetry freshness; avoid dumping prompts or hundreds of tasks.
3. Preserve the current mode and active attempt. Do not interpret development, installation, registration, or enqueue requests as permission to start real computation.
4. Read the configured deployment's own instructions before touching models. Do not assume the original author's filesystem or environments exist.

## Execution boundary

- Only `start`, `auto`, `smart`, or the UI's explicit start/apply actions enable computation. Require the user's intent to run work; no additional confirmation is needed if they already authorized that action.
- `schedule`, `smart-config`, registration, and import do not enable a mode. An already enabled queue **can run newly enqueued/retried jobs**. Read mode first; do not silently pause an authorized workload.
- `pause` finishes the current job. `stop` writes STOP and requeues unfinished work after cleanup. Stopped denoising is not resumable.
- Never write production SQLite, `runtime.json`, `safety.json`, or STOP files to bypass the public CLI. Tests may use isolated fixtures.
- Keep all heavy inference serial and inside the shared deployment `.codex-inference.lock`. Do not launch underlying model runners directly or nest resource sessions.
- The wrapper owns resident-service restoration. Never `pkill`, `killall`, or kill the shared wrapper. Only the current attempt's owned child process group may be terminated, with PID birth-time checks.
- Never disable telemetry/thermal/resource protection just to make work proceed. Missing/stale sensors block execution; protection stops latch paused until explicitly resumed.
- Registration installs trusted local code. Treat task text and JSON payloads as data; subprocesses use argv arrays, never shell interpolation.
- Delete only when requested, through `queue delete ID`. Preserve logs, inputs, failed attempts, and provenance during fixes.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export H3_QUEUE_PYTHON="$PWD/.venv/bin/python"
.venv/bin/python -m unittest discover -s tests -v
DEVELOPER_DIR=/Library/Developer/CommandLineTools ./scripts/build-app.sh
.venv/bin/python scripts/check-public.py
```

Full tests require FFmpeg/ffprobe; see [CONTRIBUTING.md](CONTRIBUTING.md). All inference tests use temporary databases, fake backends, and tiny media. Never run real model stress tests, fill disks, exhaust memory, or simulate user activity on the live desktop. `setup.command` starts the background worker; use the build script for build-only verification. Do not accept an Xcode license or change the global developer directory.

If available, prefer codebase-memory-mcp `search_graph`, `trace_path`, `get_code_snippet`, and `search_code`. Index this root under `IdleDock` if missing; older local indexes may use `queue-mac-h3`. The graph is optional tooling, not a project dependency; otherwise use `rg` and direct reads. Never commit its local index.

## Code map

| Area | Files |
| --- | --- |
| CLI, normalization, storage | `h3queue/cli.py`, `jobs.py`, `store.py` |
| Admission, execution, ownership | `worker.py`, `supervisor.py`, `resource_session.py`, `executor.py`, `processes.py` |
| Providers | `h3queue/providers/`, `tts_runner.py`, `h3_executor.py` |
| Protection, monitoring, scheduling | `safety.py`, `guarded_run.py`, `telemetry.py`, `schedule.py` |
| Provenance, recovery, estimates | `integrity.py`, `recovery.py`, `artifacts.py`, `estimate.py` |
| Native UI | `macos/` |
| UI localization | `macos/Localization.swift`, `macos/Resources/*.lproj/Localizable.strings`, [localization guide](docs/LOCALIZATION.md) |

## Changes that need particular care

- Legacy requests without `provider` mean H3. Preserve their normalized specs, fingerprints, existing rows, settings, caches, and attempt directories.
- New provider logic belongs in an adapter/manifest, not model-name branches in the scheduler. Read [docs/PROVIDERS.md](docs/PROVIDERS.md) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
- Model/input/parameter changes require a new request. `retry --refresh-deployment` only accepts reviewed entrypoint changes; `--reuse-render` is specifically for verified native-H3 delivery recovery.
- Tests must cover lock ownership, restoration, stop/retry behavior, and stale provenance when those paths change. Every retry creates a new attempt.
- Technical artifact checks are not human audio/visual acceptance. Weight inventory metadata is not a full weight-file SHA256 proof. Chip power is not wall power or a model's isolated energy use.
- Build/UI changes must preserve background work. Restart only the exact app executable when appropriate; never restart worker/supervisor/models as part of a cosmetic change.
- New UI copy needs matching resource keys in every supported catalog (currently 11 languages), including help and accessibility labels. Run `./scripts/test-localization.sh` for native localization changes. Language changes are presentation-only: never translate protocol IDs/user content or invoke queue commands when switching languages. Preserve numeric values when formatting/parsing localized settings.
- IdleDock is the public/display name. Keep legacy package names, app filename, bundle/service identifiers, data paths and CLI environment variables compatible; branding alone must not move a queue or reset preferences.
- Source preparation uses `python3 scripts/check-public.py` and `python3 scripts/export-source.py` into ignored `.build/`. Review the manifest; do not archive the whole checkout or treat a local snapshot as a published/tagged release. Read [release instructions](docs/RELEASING.md) before publishing.
- Keep machine paths, private task titles, media, logs, databases, model files, and credentials out of public docs and commits. Use `.local/` and `AGENTS.local.md` for private notes.

## Experimental Linux / ComfyUI

Read [docs/LINUX.md](docs/LINUX.md). No DGX Spark or real CUDA validation is claimed. Use actual sysfs/NVIDIA temperature readings; missing telemetry still blocks. Linux supports manual or scheduled `--no-idle`, not desktop smart mode, native UI, or launchd. The ComfyUI example owns a dedicated local server per attempt inside the GPU session and guarded process group; do not attach it to a shared server or replace owned cleanup with global API cancellation. Separate state/deployment per host; never share SQLite via a network filesystem. Mac SSH mirroring is CLI-only. Keep tests model-free.
