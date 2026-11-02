# Changelog

## 2026-11-02 — Experimental Linux worker

- Portable POSIX CLI launcher; manual and headless scheduled execution on Linux.
- Fail-closed sysfs/NVIDIA temperature telemetry with explicit sensor-path diagnostics.
- Registered ComfyUI adapter with a dedicated owned server, isolated attempts and hashed saved artifacts.
- Linux x86-64/ARM64 CI, systemd example and SSH/setup documentation.
- No DGX Spark hardware or real CUDA/model validation claimed.

## Unreleased

- Named the project IdleDock; retained legacy app filename, data/preferences, package names, service identifiers and CLI settings for compatibility.
- Added Traditional Chinese, Brazilian Portuguese and Italian, bringing the UI to 11 languages; added Chinese script/region matching and documented Portuguese fallback.

- Extended the UI to Japanese, Korean, Spanish, French, German and Russian; added region matching, locale-aware numeric displays/settings input, and catalog-wide native checks.

- Added English/Simplified Chinese UI resources, system-language defaults, persistent instant switching, localized status/help/accessibility text, and isolated native localization checks.

- Generalized the H3 queue to built-in H3/TTS and registered command providers, with one serial queue and shared resource sessions.
- Added TTS profiles, atomic batch import, typed artifact validation, and provider-specific measurements while retaining legacy H3 data compatibility.
- Updated the native widget for audio/video/file outputs and execution phases.
- Added MIT licensing, English/Chinese project overviews, setup/deployment/usage/architecture guides, and shared agent instructions for Codex, Claude Code, and WorkBuddy/CodeBuddy.
- Added a standalone session template and model-free command example.
- Made queue Python selection and host tool discovery portable; added public-source checks and a macOS test/build workflow.

No binary release, bundled model deployment, or universal runtime/quality certification is claimed by this entry.
