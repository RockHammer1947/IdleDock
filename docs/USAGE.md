# Queue operation and recovery

Commands return JSON; failures use a nonzero exit code. `--help` is the authoritative option list. Use absolute request and asset paths. Examples containing `/absolute/...` are placeholders to edit, not executable installations.

The widget supports English and Simplified Chinese. Use its gear menu → **Language / 语言** (also available in the menu bar) to switch immediately or follow the system. This preference does not change queue mode, scheduling, or TTS synthesis language. See [UI localization](LOCALIZATION.md).

## Read state before changing it

```sh
./queue status
./queue providers
./queue doctor
```

`status.settings.mode` is `paused`, `manual`, `auto`, or `smart`. `active` describes the current attempt; `counts` includes the whole database even though the returned job list is capped at 200. `telemetry.stale` means displayed readings are not fresh. Estimates without applicable same-machine samples remain unknown.

## Commands and effects

| Command | Effect |
| --- | --- |
| `enqueue FILE --title TITLE` | Validate, fingerprint, and add/reuse one job |
| `enqueue-batch FILE` | Validate and import 1–500 jobs atomically |
| `register-provider FILE [--replace]` | Install a trusted command manifest; does not start work |
| `start` | Enable immediate manual-mode execution |
| `schedule --start 23:00 --end 07:00 --timezone Asia/Shanghai --idle-minutes 10` | Save a daily window and idle requirement; does not enable it |
| `auto` | Enable the saved daily schedule |
| `smart-config --idle-minutes 10` | Save an idle threshold (1–240 minutes); does not enable it |
| `smart` | Enable idle-triggered execution at any time of day |
| `pause` | Disable further work after the current job finishes |
| `stop` | Request immediate cancellation and requeue unfinished work; mode becomes paused |
| `cancel ID` | Cancel one job; active jobs clean up before settling |
| `retry ID` | Queue a retry with a new attempt, retaining previous evidence |
| `prioritize ID` | Raise priority for the next claim; does not preempt the active job |
| `reveal ID` | Show output or attempt directory in Finder |
| `delete ID` | Move a finished job's files to Trash and invalidate its cache; explicit user action only |
| `safety` | Return current protection policy (also synchronizes its runtime configuration file) |
| `safety --set KEY=JSON_VALUE` | Update a validated protection setting |
| `calibrate-energy` | Read existing successful benchmark measurements; no generation |

Enqueue/retry does not change mode. **An enabled queue may immediately run newly queued work.** Do not use a live queue for examples; use the [isolated demo](INSTALL.md#isolated-demo). Identical fingerprints reuse existing jobs/cache after integrity checks. Each failed/stopped attempt keeps its own directory.

In `auto` mode, window end stops unfinished work by default. `schedule --finish-current` changes that policy; `--no-idle` removes the window's idle prerequisite. Set the timezone explicitly for your location (the legacy default is Asia/Shanghai). Equal start/end times mean an all-day window. Ordinary `auto` idle checks control admission; `smart` additionally stops when keyboard/mouse activity returns.

`smart` may lose the unfinished segment's compute on each interruption because model denoising has no resume checkpoint. Split long TTS scripts into natural paragraphs. A safety stop stays paused even after cooling; resume only after checking the cause. Closing the app does not stop the worker or its independent supervisor.

## Inputs and outputs

- [Text-video example](../examples/text-video.json): edit prompt/profile and dimensions for your deployment.
- [Audio-avatar template](../examples/audio-avatar.template.json): provide compatible engine, portrait, and prepared WAV paths.
- [TTS request](../examples/tts.json) / [batch](../examples/tts-batch.json): match a configured profile, language, and voice options.
- [Command manifest](../examples/command-provider.template.json): register once, then submit data-only payloads.

Batch defaults are shallow-merged with each request. Any invalid item rolls the entire batch back; duplicate input items may map to the same job ID. Batch limit is 4 MiB; individual request files are limited to 256 KiB.

`import-avatar FOLDER` is retained for the original trusted H3 plan/receipt layout, including its existing reuse/approval records. It is not a generic directory importer or a new quality check; new integrations should use explicit request JSON and `enqueue-batch`.

Default state is `.state/queue.sqlite3` (WAL). Media and logs are in `.state/runs/<job>/<attempt>/`. A custom CLI state directory can be selected with `H3_QUEUE_HOME`. Do not commit or share that directory: it contains request text, file paths, and outputs.

## Diagnose a failure

1. Read mode, active attempt, reason, telemetry freshness, and the specific job's error.
2. Inspect that attempt's `session.log`, `render.log`, `error.json`, and `receipt.json` when present. Redact prompts, paths, and identity/reference media before sharing.
3. Fix the actual missing dependency, runtime error, changed source, or resource condition. Keep failed evidence; no unlimited automatic retries.
4. For unchanged inputs/deployment, use `retry ID`. This can run immediately if the queue is still enabled.
5. For **reviewed entrypoint changes**, use `retry ID --refresh-deployment`. Input/model/parameter changes require a new request instead.
6. For a successful raw native-H3 render whose delivery failed, `retry ID --refresh-deployment --reuse-render` can redo only delivery after strict provenance validation. It is not a general model resume feature.

Do not delete a lock, disable thermal checks, edit SQLite status, or kill a wrapper to force progress. Technical success still requires human review for speech quality, visual artifacts, and lip sync.

## Backup and maintenance

Prefer a maintenance window with no active attempt. Use SQLite's backup API (or the `sqlite3` CLI `.backup`) for a coherent database snapshot; copying only `queue.sqlite3` while WAL writes continue can omit data. Also preserve `runs/`, provider manifests, and referenced external inputs/deployments. A database alone does not contain the media. Restoration/migration of a real queue should be reviewed explicitly; do not overwrite an existing `.state` from a demo.
