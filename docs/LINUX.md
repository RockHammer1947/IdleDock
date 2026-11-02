# Experimental Linux CLI worker and ComfyUI

IdleDock can run as a **headless Python CLI/worker on Linux**, including an
ARM64 deployment such as a DGX Spark. The SwiftUI app remains macOS-only.
**We do not own a DGX Spark and have not tested this on DGX hardware or run a
real CUDA/ComfyUI model with this adapter.** See GitHub Actions for the actual
Linux x86-64/ARM64 fake-runtime results; CI is not GPU validation.

This first version supports one serial queue per host, manual execution and
scheduled windows without desktop idle detection. H3 and MLX TTS remain Mac
integrations. Bring your own Linux/CUDA program through the
[command provider protocol](PROVIDERS.md), or try the ComfyUI adapter below.
There is no two-Spark load balancing, shared database over a network filesystem,
remote SwiftUI connection, or Linux desktop idle detector. Do not use `smart` on
Linux. For schedules use `schedule --no-idle`, then explicitly enable `auto`.

## Install the queue, without starting inference

Python 3.10+ and `python3-venv` are required. FFmpeg/ffprobe is needed for video
validation and the full test suite, not for the ComfyUI output bundle.
Install prerequisites with your distribution package manager. NVIDIA drivers,
CUDA, ComfyUI, custom nodes and weights are separate existing installations.
Do not use `setup.command`, `build-app.sh`, or `launch-agent` on Linux.

```sh
cd "$HOME"
git clone https://github.com/RockHammer1947/IdleDock.git
cd IdleDock
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export H3_QUEUE_PYTHON="$PWD/.venv/bin/python"
export H3_QUEUE_HOME="$HOME/.local/share/idledock"
./queue status
./queue doctor
./queue providers
```

A new state directory is paused. Existing queues keep their mode. This does not
install models or enable computation. Each Spark needs a separate local state
and deployment directory; copying requests to both machines will run them twice.

## Temperature protection is required

Linux uses actual CPU/SoC temperatures from sysfs hwmon/thermal zones and GPU
temperatures from `nvidia-smi` or GPU/SoC sysfs sensors. It uses the maximum of
recognized readings, including all returned NVIDIA GPUs. It reports no chip or
wall energy estimate: GPU board power is not whole-chip/whole-system power.
Missing, invalid or stale CPU/GPU readings **block execution**. Do not disable
`require_telemetry` or overheat protection to get a job running.

`queue doctor` includes `linux_sensor_probe` with readings, source paths and
sensor errors. On a Spark, `nvidia-smi` fields and sysfs names may differ with
DGX OS/driver versions. If automatic detection cannot identify real sensors,
inspect `/sys/class/hwmon/` and `/sys/class/thermal/` and explicitly select
verified **millidegree Celsius** files. Do not select a disk/ambient sensor as a
CPU or GPU substitute. A documented shared SoC junction sensor may protect both.

```sh
# Examples only; choose the actual files on this host before setting these.
export H3_QUEUE_CPU_TEMP_PATHS='["/sys/class/thermal/thermal_zone0/temp"]'
export H3_QUEUE_GPU_TEMP_PATHS='["/sys/class/thermal/thermal_zone1/temp"]'
# Optional: absolute installed tool, if nvidia-smi is not on PATH.
# export H3_QUEUE_NVIDIA_SMI=/absolute/path/to/nvidia-smi
./queue doctor
```

Overrides must be nonempty JSON arrays of absolute paths resolving under `/sys`.
An invalid override fails closed. Set them in the worker's environment before
starting it; add reviewed `Environment=` lines to the systemd unit if using it.
If CPU/GPU temperatures are unavailable on your Spark, please report sanitized
sensor names/paths, DGX OS, driver and `nvidia-smi` availability so we can add a
proper backend. Do not post private task data, network addresses or credentials.

## Prepare an existing ComfyUI installation

The adapter starts a **dedicated loopback ComfyUI instance for each attempt**,
using your installed environment. The worker owns its entire process group.
It does not attach to, stop, clear, or interrupt an existing ComfyUI server.
This deliberately avoids ambiguous remote cancellation and duplicate submissions
after disconnects. Per-attempt loading is slower than a persistent model server.
Keep an independently running GPU server/workload off the same compute resource
while using this queue, or integrate that resident service with the
[deployment session](DEPLOYMENT.md). The cooperative lock cannot control
external processes that ignore it.

```sh
.venv/bin/python scripts/prepare-comfyui.py "$HOME/.config/idledock-comfy" \
  --comfy-root /absolute/path/to/ComfyUI \
  --comfy-python /absolute/path/to/comfy-venv/bin/python
```

This writes reviewed configuration, a GPU provider manifest, and a new standalone
session to a **new** directory. It does not register/start anything and refuses
to overwrite. Review `comfy-config.json` and `provider.json`. The adapter requires
ComfyUI's `--listen`, `--port`, `--input-directory`, `--output-directory`, and
`--disable-auto-launch` flags, plus `/system_stats`, `/prompt` and
`/history/{prompt_id}` APIs. Check your installed ComfyUI version supports them.
It proves its child owns the listening port before submitting any workflow.
It uses the queue Python/psutil for control and the ComfyUI Python for inference.

The supplied standalone session is suitable when no resident service needs
suspending/restoring. **Do not replace an existing managed deployment** with it.
If you already have one, register the provider against that deployment instead.

```sh
./queue configure --deployment "$HOME/.config/idledock-comfy/deployment"
./queue register-provider "$HOME/.config/idledock-comfy/provider.json"
./queue providers
```

## Submit an API workflow

Export your workflow using ComfyUI's **API format**, not its visual-editor graph.
Models/custom nodes must already be installed in your ComfyUI environment.
Include at least one save/output node; preview-only workflows fail explicitly.
Save this as `request.json`, replacing the absolute workflow path:

```json
{
  "schema_version": 1,
  "provider": "comfyui",
  "profile": "default",
  "assets": {"workflow": "/absolute/path/to/workflow.api.json"},
  "payload": {}
}
```

Optional `payload.inputs` replaces existing node inputs, for example
`{"inputs":{"6":{"text":"A quiet workshop at dawn"},"3":{"seed":42}}}`.
Use the actual node/input IDs from your workflow. It cannot replace executables
or server arguments. Other asset keys are plain filenames, e.g.
`"reference.png":"/absolute/path/to/reference.png"`; each is copied into the
attempt's isolated ComfyUI input directory. The workflow must reference that
filename. External/absolute paths embedded inside custom-node workflows are not
sandboxed or automatically hashed. Declare all input files in `assets`, keep
models immutable, and review workflows/custom nodes as trusted local code.

The workflow, input assets, config, runner and selected ComfyUI entrypoint files
are hashed. This does not prove the identity of every custom node, installed
package or weight file. Reconfigure/re-register reviewed installation changes;
model/parameter/input changes require a new request, not an old cache hit.

```sh
./queue enqueue request.json --title 'ComfyUI test'
./queue status
```

Enqueue ensures a background worker exists, but does not enable a paused
queue. If the queue was already enabled, the new job can execute. Set sensor
environment variables before the first enqueue/init/control command; a running
worker keeps its existing environment. For a foreground worker, start
`./queue worker` in a second terminal **before enqueueing**. For systemd, install
and start the service **before enqueueing** instead. Do not run another worker
alongside it; the singleton lock makes later workers exit without taking over.

After `queue status` shows fresh temperature telemetry, explicitly authorize work:

```sh
./queue start
./queue status
```

`pause` finishes the current item; `stop` terminates the owned ComfyUI instance
and requeues unfinished work. `cancel ID` terminates/cancels that job. A stopped
workflow has no resumable denoising checkpoint. Each retry uses a new attempt
and new isolated input/output directories. Failed logs and outputs are kept.
The primary output is `comfy-result.zip`, containing saved outputs and a
`manifest.json` with filenames, sizes and SHA256s. The queue hashes the entire
bundle so cache integrity covers the media, not only a list of filenames. This
is file integrity, **not** media decode or human quality acceptance. Custom nodes must
keep output under the supplied output directory and not daemonize outside the
owned process group. The adapter never calls global `/interrupt` or clears a
shared server's queue. Queue lifecycle timeout, memory/swap/disk and thermal
guards apply to the entire owned process group.

## Optional user systemd service

For a checkout at `~/IdleDock`, inspect [the sample unit](../examples/linux/idledock.service),
edit paths/environment if needed, and install it yourself:

```sh
mkdir -p "$HOME/.config/systemd/user"
cp examples/linux/idledock.service "$HOME/.config/systemd/user/idledock.service"
systemctl --user daemon-reload
systemctl --user enable --now idledock.service
journalctl --user -u idledock.service -n 50
```

Install the service before the first enqueue/init if you want systemd to own
the worker. It cannot take over an already running detached worker. The unit
must use the same `H3_QUEUE_HOME`, sensor overrides and deployment as the CLI. A new queue stays paused. An existing enabled mode can run pending jobs
as soon as the service starts. Do not run a second foreground worker alongside
it. The singleton lock prevents duplicate workers. `KillMode=process` preserves
independent attempt supervision across worker restarts; use `queue stop` and
wait for cleanup **before** stopping the service or upgrading dependencies.
User services without login/linger may stop at logout; decide with your system
administrator whether persistent user services are appropriate.

## Use the Mac as an SSH terminal/mirror

Keep the state/database on the Spark, not a mounted/network SQLite directory.
From the Mac, run the Spark CLI through SSH (substitute your SSH host alias and
actual checkout/state paths):

```sh
ssh spark-a 'cd "$HOME/IdleDock" && H3_QUEUE_HOME="$HOME/.local/share/idledock" ./queue status'
ssh spark-b 'cd "$HOME/IdleDock" && H3_QUEUE_HOME="$HOME/.local/share/idledock" ./queue status'
```

Use SSH/SCP for requests/results as needed. The Mac native widget does not yet
mirror remote queues. No network control service or public inference port is
added by this feature.

## Feedback and contributions

Please try a small known-working workflow first. We need real DGX Spark feedback
on sensor discovery, ARM64 environments, ComfyUI flags/custom nodes, cancellation
and output nodes. Open an [issue](https://github.com/RockHammer1947/IdleDock/issues)
with OS/architecture, Python, driver/ComfyUI versions and sanitized errors, or
send a [pull request](https://github.com/RockHammer1947/IdleDock/pulls).
Do not publish complete `.state` directories, media, secrets or private prompts.
Follow [CONTRIBUTING.md](../CONTRIBUTING.md); tests use fake servers/sensors and
must not start real GPU stress workloads.
