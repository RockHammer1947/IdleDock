# Preparing an IdleDock source release

The repository is licensed under MIT. Publishing a repository or release is a separate maintainer action; preparing files locally does not publish them.

IdleDock is the public name. The initial UI scope is 11 languages. The app display name is IdleDock; legacy package names, `H3 Queue.app` filename, service/bundle identifiers and queue paths remain compatible. Do not rename internal state or migrate a user's queue as part of branding.

## Before publishing

- Review the intended repository name/owner and the MIT copyright notice; inspect the final file list and diff.
- Run the checks in [CONTRIBUTING.md](../CONTRIBUTING.md), including `scripts/check-public.py`.
- Review Git history as well as the working tree for secrets, personal paths, private requests/media, databases, logs, graph indexes, environments, and model weights. `.gitignore` alone does not clean history.
- Keep local reports and machine-specific instructions in ignored `.local/` / `AGENTS.local.md`; preserve them locally instead of deleting operating history.
- Confirm examples use synthetic data and portable placeholders. Run the model-free demo from a fresh source export with no access to the author's deployment.
- Confirm [DEPLOYMENT.md](DEPLOYMENT.md) accurately describes missing external H3 assets and TTS runtime requirements. Do not market the source as a one-click H3/model installation.
- After choosing the public hosting location, enable a private vulnerability-reporting channel and update [SECURITY.md](../SECURITY.md) if needed. Do not invent a maintainer contact.
- Run a fresh session in each available agent client with the [onboarding prompt](AGENT_GUIDE.md#copyable-first-session-prompt), checking instruction loading and mode preservation. Documentation checks are not a substitute for client testing.

## Source packaging

Publish only the reviewed source files in version control. Do not zip the entire working directory: ignored runtime data remains on disk. After committing the reviewed source, use `git archive` at the intended tag/commit to produce a source archive. Review its manifest before distributing it.

Before the first commit, or to review a working source snapshot, run:

```sh
python3 scripts/check-public.py
python3 scripts/export-source.py
```

This writes `.build/releases/idledock-source.zip`, a per-file checksum/permission manifest, and an archive SHA256 sidecar. It uses Git's public candidate list (tracked plus non-ignored new files), requires the public checks to pass, preserves executable bits, excludes history and ignored runtime data, verifies archive contents, and refuses to overwrite existing exports. Choose a new ignored output path with `--output` when repeating it. The export is a working-tree snapshot, not a commit/tag or proof that hosted CI ran. Review the manifest and unpack it into an isolated directory for a clean-install check.

In the source tree, confirm `git remote -v` and the intended owner/repository before publishing. If no remote or initial commit exists, the project is prepared locally only; do not report a public GitHub URL, tag or release as created.

The `.github/workflows/ci.yml` workflow verifies fake-runtime tests, public-source checks, native compilation, and ad-hoc signature validity. It has no publishing step. Check its first hosted result after publication; local tests alone do not prove that hosted CI passed.

## Binary releases are separate work

The current build embeds absolute checkout/Python paths, and the runtime expects external tools and deployments. Do not upload `dist/H3 Queue.app` as a general installer. A future binary release needs a relocatable runtime/configuration design, dependency/notice packaging, an installer/update strategy, and an explicit signing/notarization plan. Keep source-release claims separate from those milestones.
