# External deployment contract

The repository owns scheduling, process supervision, validation, and the native UI. It does **not** supply a universal model installation. A deployment is a local directory containing the session integration and any provider-specific configuration. Configure it with `queue configure --deployment /absolute/deployment` before starting a new worker.

## Command and TTS sessions

The queue acquires `<deployment>/.codex-inference.lock` using an exclusive `flock`. Every external participant sharing this compute resource must use the **same file**, including across queues/checkouts. Different deployment roots produce different locks. Never delete a live lock file to unlock it.

While holding the lock, the queue imports `<deployment>/agent_session.py`. Importing this module must not run inference, parse CLI arguments, acquire the lock again, or start/stop services. GPU providers call:

```python
service('status')
# Return {'running': False, 'state': None}, or:
# {'running': True, 'state': {'profile': 'profile-id', 'prefix_cache': False}}

service('stop')                              # only if originally running
service('start', previous_profile, prefix_cache)
ready(previous_profile)                      # wait until restored; raise on failure
```

Functions must raise when an operation fails; returning a failure dictionary is insufficient. `stop` must return only after releasing the resident service's compute resources. `start`/`ready` restore its prior configuration. These helpers must not acquire `.codex-inference.lock` themselves: the queue already holds it. Their original implementation controls a resident Qwen service, but the protocol can wrap another service. CPU providers hold the lock and import the module without calling these service helpers.

If there is **no resident model service to manage**, copy the [standalone session template](../examples/standalone-deployment/agent_session.py) into a new deployment directory. It declares that no resident service is configured; it does not inspect or stop other GPU workloads. This makes command providers, and separately installed TTS profiles, usable without the original H3/Qwen installation. Do not replace an existing managed session with this template.

The wrapper lock covers execution, cleanup, and service restoration. Task text cannot change session configuration. This is a cooperative local protocol, not a sandbox, hardware partition, or protection from unrelated programs.

## Registered commands

Use [examples/command-provider.template.json](../examples/command-provider.template.json). Supply installed absolute executable/script paths, declared dependency files, a resource requirement, and an output kind. Registration copies the manifest into the queue state. Requests contain data and asset paths; they cannot replace the executable. See the complete [provider protocol](PROVIDERS.md).

The [echo runner](../examples/echo-provider/runner.py) is a complete minimal implementation. `scripts/prepare-demo.py` generates absolute-path configuration for it without registering, enqueueing, or starting work.

## TTS profiles

Create `<deployment>/TTS/profiles.json`, a JSON object keyed by profile IDs. Start with [tts-profiles.template.json](../examples/tts-profiles.template.json):

| Field | Meaning |
| --- | --- |
| `family` | Human-readable model family |
| `runtime` | `mlx-audio`, `mlx-audio-plus`, `indextts`, or `auk` |
| `python` | Absolute executable of that runtime's environment |
| `model_path` | Absolute model directory, or relative to `<deployment>/TTS` |
| `languages` | Accepted request language codes, e.g. `zh`, `en` |
| `reference` | Whether this profile requires reference audio |
| `generation` | Optional runtime-specific generation defaults |

Install dependencies and weights separately according to the runtime/model's own instructions and licenses. No weights or environments are downloaded by the queue. The runner sets Hugging Face/Transformers offline variables. Pin your own known-working runtime version; the adapter interface is not a promise of compatibility with every upstream release.

Current adapter expectations are encoded in [tts_runner.py](../h3queue/tts_runner.py): MLX runtimes provide `mlx_audio.tts.utils.load_model(...).generate(...)`; IndexTTS provides `mlx_indextts.runtime.TTSRuntime` / `GenerateOptions`; AuK provides `auk_mlx.infer.AukMLX` / `GenerateOptions`. All currently rely on MLX. IndexTTS also expects `TTS/runtimes/models/w2v-bert-2.0`; AuK expects its config YAML and `qwen` directory beneath the model directory.

Some profile IDs select model-specific defaults: `qwen-custom`, `qwen-base`, `kokoro`, and AuK IDs ending in `flash`. Keep those IDs when using those adapters; an arbitrary renamed profile may require adjusted generation options or an adapter change. Reference profiles require non-silent PCM16 WAV (mono/stereo, 8–192 kHz, longer than 0.1 s and at most 60 s). `qwen-base`, `ming`, and `fish-drama3` also require an exact reference transcript. `indextts` and `auk` should declare `reference: true`.

Use `queue providers` for discovery, then start from [tts.json](../examples/tts.json) or [tts-batch.json](../examples/tts-batch.json). File presence is a configuration check, not synthesis validation. A real smoke synthesis must be explicitly authorized and subsequently listened to.

## Legacy H3

The existing adapter assumes this layout:

```text
deployment/
  agent_session.py
  Qwen3.8/.venv/bin/python
  H3/
    minimax-h3-mlx/.venv/bin/python
    generate_fast.py
    resource_monitor.py
    models/MiniMax-H3/
```

The `Qwen3.8` directory is a legacy path name, not a package to install from this repository. The H3 environment must include `psutil` because the guarded executor runs there. FFmpeg/ffprobe must be available on the host. `resource_monitor.py` is retained in legacy deployment provenance.

The supervisor invokes the existing wrapper as:

```text
<session-python> <deployment>/agent_session.py h3 -- <h3-python> -m h3queue.executor <attempt-request>
```

That wrapper must hold the same lock, suspend a resident Qwen service when appropriate, set `LOCAL_MODEL_SESSION_TARGET=h3`, execute the command, wait for owned cleanup, and restore the prior service even on failure/stop. The standalone template does **not** implement this CLI.

`generate_fast.py` must accept the profile/prompt-file/width/height/frames/seed/out arguments emitted by [h3_executor.py](../h3queue/h3_executor.py). Profiles currently accepted are `native20`, `lightx3`, and `tf3`; availability depends on your deployment. The adapter expects an output video with an audio stream. Width/height are multiples of 32 and profile frames are `3n+1`.

`native-audio` needs an independently patched engine supporting the exact `--audio-drive`/`--first-frame` invocation and `audio-drive invariant PASS` signal checked by the executor. It accepts `native20` only, uses `17n+5` frames, and takes already prepared 2–15 second WAV input. An unmodified upstream engine is not equivalent. `trim_s`/`delivery_frames` affect delivery, not the driving clock. This repository neither distributes that engine nor offers a fresh H3 deployment installer.

## Updates and provenance

Keep model deployments immutable while jobs are pending. The queue snapshots configuration, hashes declared inputs/entrypoints, and stores TTS model file inventory metadata. Inventory paths/size/mtime are not full hashes of all weights. Change model/input/parameters by enqueueing a new request. For a reviewed code-only deployment change, `retry ID --refresh-deployment` can refresh permitted pins; do not edit stored job specs.
