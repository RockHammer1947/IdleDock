# Third-party components and model boundary

The [MIT license](LICENSE) applies to this repository's code and documentation. It does not change the licenses of dependencies, models, model weights, datasets, voices, or user-provided media. No model binaries or private deployment scripts are included in the public source set.

| Component | Use | Distribution here |
| --- | --- | --- |
| Python and SQLite | Control plane and local database | Host/runtime dependencies |
| [psutil](https://github.com/giampaolo/psutil) | Process ownership and memory monitoring | Installed separately via `requirements.txt` |
| [FFmpeg](https://ffmpeg.org/legal.html) | Video encoding, decoding, probing | Host tool, not bundled; license depends on the selected build |
| [macmon](https://github.com/vladkens/macmon) | Apple Silicon sensor sampling | Host tool, not bundled |
| Apple SDKs/frameworks | SwiftUI/AppKit application | Provided by the user's development environment/macOS |
| H3 / MLX / TTS runtimes and models | External inference | User-installed; versions and licenses must be reviewed separately |

The runnable echo provider and standalone session template are original repository examples under MIT. The template is not a copy of the original deployment and does not implement its H3 command-line wrapper. If distributing packaged binaries later, reassess notices and redistribution terms for every bundled component; a source-only dependency reference is different from redistributing a binary or weight file.
