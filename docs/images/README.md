# UI screenshots

`queue.jpg` / `system.jpg` (Chinese) and `queue-en.jpg` / `system-en.jpg` (English) are window captures of the implemented SwiftUI/AppKit application, using [preview-status.json](preview-status.json). The fixture contains invented task names, progress, and monitoring values; it contains no real queue records or model outputs. Queue-changing controls are disabled by preview mode. User-authored task names stay in their original language in both versions.

To refresh the screenshots:

1. Build the app using the build-only command in [CONTRIBUTING.md](../../CONTRIBUTING.md).
2. Copy the app into an ignored `.build/` directory and give the copy a separate bundle identifier so its window/preferences remain independent from the normal app.
3. Set `preview` in the copy's `Contents/Resources/config.json` to the absolute path of this fixture. Set `python` to `/usr/bin/false` as a further safeguard; preview mode reads JSON instead of executing queue commands. Re-sign the modified copy locally with `codesign --force --sign -`.
4. Open that copy and use its gear menu → Language / 语言 to select the screenshot language. Capture the queue and system tabs, and visually check that neither screenshot includes private information. Capture only its window; do not include the desktop or other apps.
5. Close the preview copy. Do not change or restart the production worker, model session, or regular application to take documentation screenshots.

Screenshots are intentionally stored under `docs/images/` so both README translations work on GitHub and in a local checkout. The public-source check permits PNG/JPEG screenshots only in this directory, checks their signature/size, and continues rejecting runtime media elsewhere. Visual review remains necessary; the script cannot determine whether pixels contain private information.
