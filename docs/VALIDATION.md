# IdleDock source preparation validation

Recorded 2026-10-30 on an Apple Silicon Mac with Python 3.12.13 and psutil 7.2.2. These are local results for the prepared source, not hosted CI results or real-model quality certification.

| Check | Result |
| --- | --- |
| Full Python suite | 88 tests passed using temporary databases, fake runtimes, and tiny media |
| Exported source in a fresh checkout | 88 tests passed again with a new venv; no queue state, model deployment, or environment was included in the export |
| Native application | Built from both the working source and the clean export; ad-hoc signatures verified |
| UI catalogs | 11 complete catalogs, 268 messages each; keys, native language names and format arguments checked |
| Native localization | All bundled tables/formats, language fallback, region/script matching, persistence, repeated switching, unchanged queue state, and preview write refusal passed |
| Numeric settings | Decimal-comma display and numeric parsing round trips passed, including Portuguese and Italian |
| Visual previews | New Traditional Chinese, Brazilian Portuguese and Italian task pages inspected; earlier six added languages and long Russian protection settings also inspected in read-only previews |
| Branding compatibility | IdleDock display name verified; legacy app filename, package/service identifiers, data paths and preferences retained |
| System usage checks | Swift checks passed in the clean checkout, including a lightweight live CPU sample |
| Standalone example | Fake-runtime integration tests verify execution/output; clean CLI prepare/configure/register/status succeeded with paused mode and no worker/model start |
| Source export | Manifest, checksums, executable permissions, overwrite refusal, exclusion of ignored state, and rejection of tracked runtime files/symlinks tested |
| Public-source hygiene | 100 source candidates checked: local documentation links, example JSON, selected private path/key patterns, and excluded runtime files |
| Shell / workflow | Shell syntax checked; CI includes fake-runtime tests, source export, native build/signature checks and localization checks |

The prepared source archive contains code, documentation, examples and reviewed screenshots. A per-file SHA256/permission manifest and an archive SHA256 sidecar accompany the local export. It contains no Git history, runtime databases/logs, local model weights, environments, generated app bundles or private machine instructions. The export is a working-tree snapshot, not a tagged release.

Tests did not start real H3/TTS inference or alter production queue mode. The clean CLI configuration used the standalone example deployment in an isolated queue home. Screenshots/previews use invented task names and monitoring data. A focused file check is not a comprehensive secrets audit; translations have not received universal native-speaker approval.

Still to validate after public hosting: the first hosted GitHub Actions run (including Python 3.10), repository security-reporting settings, and onboarding in actual sessions of each agent client/version. Each real model/runtime also needs its own synthesis and quality checks. A portable signed/notarized binary installer remains separate work; the current release preparation is for source distribution.

## Publication preparation — 2026-11-01

The checkout is now named IdleDock. Its existing local installation retained the previous path through a filesystem symlink; production task counts, execution mode and live worker telemetry were preserved. Legacy app/service identifiers and stored history were not rewritten.

Revalidated with Python 3.12.13 and psutil 7.2.2:

- All 88 Python tests passed in the working checkout and again from a reviewed, freshly extracted source snapshot using an isolated venv.
- Native builds and ad-hoc signature verification passed in both locations. System-usage and 11-language native localization checks passed, including preview write refusal and unchanged queue state.
- The live CPU sampling check now waits up to two seconds for counters to advance, instead of assuming every 100ms sample changes. Deterministic unknown/stale-counter checks remain unchanged.
- The clean source's standalone demo was prepared, configured and registered in an isolated paused queue; this CLI smoke check did not start a worker or model. Fake-runtime tests cover execution.
- The 100 public source candidates passed documentation/example/private-file checks and a redacted Gitleaks scan. Source archive checksums, executable permissions and file manifests were reviewed. Models, runtime state, media, environments, build caches and local machine notes are excluded.
- GitHub private vulnerability reporting is enabled; see [the security policy](../SECURITY.md).

These are local source-preparation results. Hosted runs are available under [GitHub Actions](https://github.com/RockHammer1947/IdleDock/actions/workflows/ci.yml). Actual onboarding sessions in every supported agent client/version, native-speaker review of every translation, real-model compatibility/quality, and portable signed/notarized binary distribution remain separate validation work.
