# Security and privacy

This is a local desktop tool, not a sandbox for untrusted programs. A registered provider and deployment session execute with your user's permissions. Review their code and declared dependencies before registering/configuring them. The shared file lock is cooperative; it cannot stop an unrelated GPU process.

Requests and model text are data. Keep them out of shell interpolation. The built-in queue does not expose a web service or upload telemetry. External providers are ordinary programs and may have their own network behavior; only the built-in TTS runner sets the documented offline environment variables.

`.state/` contains private task text, absolute file paths, logs, outputs, provider configuration, and measurements. `.local/`, `AGENTS.local.md`, local graph indexes, build artifacts, and virtual environments are ignored by Git. Ignore rules do not remove files already committed. Check staged files and history before publication; use synthetic fixtures in issues and tests.

Do not post credentials, reference voices/faces, customer prompts, private deployment paths, or a database in a public issue. Report security vulnerabilities through [GitHub private vulnerability reporting](https://github.com/RockHammer1947/IdleDock/security/advisories/new), also available under **Security → Report a vulnerability**. Keep sensitive exploit details in that private channel.

There is currently no security SLA or formal supported-version policy. Fixes target the active development branch. This source release is locally built/ad-hoc signed; it is not notarized or an assurance that arbitrary third-party runtimes are safe. Hardware guards supplement macOS protection and do not replace it.
