# Source provenance

The dependency recipes fetch immutable upstream archives and verify SHA-256:

| Source | Revision | SHA-256 |
| --- | --- | --- |
| Howdy | `d3ab99382f88f043d15f15c1450ab69433892a1c` | `e0b58928c6d1362ea8c630f056261bccb446fe84b507f7b7cceb7c5a55706061` |
| dlib | `v20.0.1` | `dab5b4ec4b68bd7dc128a1fb7900723f89d2da107e44cd5def7d38fc57252a9d` |
| dlib recognition model | upstream file | `abb1f61041e434465855ce81c2bd546e830d28bcbed8d27ffbe5bb408b11553a` |
| dlib landmark model | upstream file | `6e787bbebf5c9efdb793f6cd1f023230c4413306605f24f299f12869f95aa472` |

The dlib recipe uses a CPU-only build and limits compilation to two jobs. Howdy is
packaged without its PAM policy or GTK manager because this plugin owns those
interfaces. No fetched source or binary archive is committed to the repository.

`plugin/Service.qml` and `plugin/LockView.qml` derive from Omarchy's MIT-licensed
lock plugin. The manifest declares `omarchy.clonedFrom: omarchy.lock`, allowing
the host to grant the same authentication capability while retaining stock
password and fingerprint behavior.
