# Source provenance

The dependency recipes fetch immutable upstream archives and verify SHA-256:

| Source | Revision | SHA-256 |
| --- | --- | --- |
| howdy-next 3.4.0 | `b0b3d290cbd38a0a44f6bf0a37b414210acf8276` | `8454f74ae48f3284b25b74c16ab6f9806ba2b8b1857a6c5f740c8c62b24937fd` |
| YuNet detector | OpenCV Zoo `26cc381e4d2594bb9f47a26eb8fd96c94a13660d` | `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0` |
| SFace recognizer | OpenCV Zoo `088c3571ec70df15100a5e4c26894d95951e92e9` | `2b0e941e6f16cc048c20aee0c8e31f569118f65d702914540f7bfdc14048d78a` |

The package uses howdy-next's native C++23 PAM and CLI implementation. Both ONNX
models are installed by the package, so authentication and enrollment never
download code or model data. Build parallelism is limited to two jobs. No fetched
source or binary archive is committed to the repository.

`plugin/Service.qml` and `plugin/LockView.qml` derive from Omarchy's MIT-licensed
lock plugin. The manifest declares `omarchy.clonedFrom: omarchy.lock`, allowing
the host to grant the same authentication capability while retaining stock
password and fingerprint behavior.

`patches/UPSTREAM_SHA256` records the exact stock Omarchy lock files used for
the clone. `patches/face-lock.patch` contains only this plugin's integration.
