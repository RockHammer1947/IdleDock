# Codex, Claude Code, WorkBuddy, and other agents

Use [AGENTS.md](../AGENTS.md) as the single source of project instructions. This guide explains how to enter the project and operate it without accidentally starting expensive inference.

## Instruction entry points

| Agent | Repository entry | Verification |
| --- | --- | --- |
| Codex | Root `AGENTS.md` | Ask it to list loaded instruction sources and summarize the compute boundary |
| Claude Code | Root `CLAUDE.md` imports `@AGENTS.md` | Use `/context` to confirm memory files, then ask for the boundary summary |
| WorkBuddy / CodeBuddy | Root `CODEBUDDY.md` points to `AGENTS.md` and this guide | Open this checkout as the project and ask it to confirm it read both files |
| Other agents | Explicitly ask to read `AGENTS.md` and this guide | Verify the same rules before giving queue commands |

Codex discovers project `AGENTS.md` instructions from the repository path. See the [official discovery rules](https://learn.chatgpt.com/docs/agent-configuration/agents-md). Claude Code supports importing shared instructions through `@AGENTS.md`; we keep that bridge for sessions/configurations that use `CLAUDE.md`. See [Claude Code memory documentation](https://code.claude.com/docs/en/memory#share-one-file-with-other-coding-tools). WorkBuddy documents compatibility with `CODEBUDDY.md`, `.codebuddy/CODEBUDDY.md`, and `AGENTS.md`; see [WorkBuddy project configuration](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Project).

Client versions, workspace trust, user/global policies, and disabled project instructions can affect loading. If it did not load the files, explicitly request that it read them; do not compensate by enabling broad permissions. These files are instructions, not an OS sandbox or a guarantee of agent behavior.

`AGENTS.local.md` is an optional **explicit-read convention of this repository**, not a cross-agent standard filename. Store private deployment paths and current machine restrictions there; Git ignores it. Canonical instructions tell each agent to read it if present. Avoid duplicating operational rules in three separate agent files.

## Copyable first-session prompt

```text
Read AGENTS.md and docs/AGENT_GUIDE.md in this checkout, plus AGENTS.local.md
if it exists. Tell me the instruction files you read. Inspect queue status,
doctor, and providers, then summarize mode, counts, active task, telemetry
freshness, and missing setup. Preserve the current mode and active attempts.
Do not start real inference, change safety settings, or download models.
```

中文版本：

```text
先读当前项目的 AGENTS.md、docs/AGENT_GUIDE.md，以及存在时的 AGENTS.local.md。
说明你读到的规则文件，检查 queue status、doctor、providers，简要汇报模式、
数量、当前任务、温度读数是否过期以及缺少的配置。保留当前模式和活跃任务。
不要启动真实推理、修改保护阈值或下载模型。
```

## Small, structured status

Run from the root with the configured queue interpreter (replace `.venv/bin/python` if using an existing environment):

```sh
./queue status | .venv/bin/python -c '
import json,sys
d=json.load(sys.stdin)
a=d.get("active") or {}
print(json.dumps({
  "mode":d["settings"]["mode"], "counts":d["counts"],
  "active":{k:a.get(k) for k in ("id","status","phase","stop_requested")},
  "reason":d["reason"], "worker_alive":d["worker_alive"],
  "telemetry_stale":d["telemetry"]["stale"],
  "estimate_seconds":d["estimate_seconds"],
  "unknown_estimates":d["unknown_estimates"]
},ensure_ascii=False,indent=2))'
```

When called from another project, use the checkout's absolute `queue` path. The CLI is the stable integration surface; agents do not need a GUI automation connection or an MCP server to use it. Some read commands initialize an absent database, but do not start models. Nonzero exit means failure; never treat an `error` JSON response as success.

## Operation boundaries

| User intent | Agent action |
| --- | --- |
| Understand/diagnose/build the project | Read status/configuration, inspect code, run isolated tests, build app only |
| Prepare batch voice/video requests | Validate files/profile; check mode before enqueueing because an enabled queue can run new jobs |
| Add a provider | Review installed executable/dependencies, register it, verify catalog; no inference authorization implied |
| Start/continue the queue explicitly | Use the requested `start`, `auto`, or `smart` action; first inspect current state and protection reason |
| Finish current item then pause | `queue pause` |
| Stop immediately | `queue stop`; wait for owned cleanup and restoration |
| Delete finished results explicitly | `queue delete ID`; do not directly remove attempt directories |

Registration runs trusted code later. Requests are JSON data; never construct shell code from text, titles, or assets. Keep inference inside the resource session; never benchmark a model directly to test a queue fix. Do not ask again for authorization already given, but an enqueue/build request is not itself permission to enable a paused queue.

## Add a new provider

1. Read [DEPLOYMENT.md](DEPLOYMENT.md) and [PROVIDERS.md](PROVIDERS.md).
2. Prefer a command manifest for an existing executable. Use a Python adapter only if custom normalization or validation is needed.
3. Declare GPU/CPU, memory reserve, immutable dependencies, output kind, and revision. Jobs cannot lower these requirements.
4. Use the JSON request/output protocol and `ExecutionContext.run` for managed child processes. Do not daemonize inference or acquire the session lock again inside a task.
5. Add isolated fake-runtime tests for success, failure, stop, restoration, changed inputs/dependencies, and output validation as applicable.
6. Document required runtime/model versions and the real-model validation still outstanding. Update CLI examples and provider docs together.

## Agent onboarding acceptance

A useful first session should identify: one serial queue; external model installations; mode preservation; enqueue versus start; pause versus stop; shared lock and restoration; mandatory fresh telemetry; isolated fake tests; and technical versus human acceptance. If an agent proposes raw SQLite edits, direct model calls, or disabling guards, correct its understanding before it acts.

The instructions have been checked against the linked official documentation. That is not a claim that live sessions of every agent client have been exercised on every version.
