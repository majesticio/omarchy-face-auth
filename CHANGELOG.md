# Changelog

## 0.5.0 — 2026-09-12

- Replace classic Python/dlib Howdy with commit-pinned howdy-next 3.4.0 and
  checksum-pinned YuNet/SFace models, removing the long local dlib build.
- Delegate profile removal and clearing to howdy-next's locked, atomic storage.
- Stage privileged installer inputs under a private root-owned directory and
  validate every file before execution.
- Add a reproducible patch and rollback-safe resync workflow for the Omarchy lock
  clone.
- Move the filled approval highlight with left/right keyboard selection.
- Document the one-time re-enrollment required by the new embedding format.

## 0.4.0 — 2026-09-12

- Replace laptop, username, UID, group, path, and camera assumptions with verified
  install-time discovery and a root-owned installation identity.
- Consolidate the lock service and manager widget into one marketplace-compatible
  root plugin manifest.
- Add conservative IR-only V4L2 detection, transactional installation/removal,
  exact recovery files, and persistent single-user configuration.
- Pin Howdy, dlib, and model downloads to immutable sources with verified hashes.
- Remove obsolete terminal confirmation, local deployment scripts, artifacts, and
  machine-specific documentation.
- Retain command-bound sudo approval, immediate screen unlock, password-protected
  profile management, theme-aware overlays, and fail-closed validation.

## 0.3.0 — 2026-09-12

- Add the native sudo approval overlay, profile manager, immediate screen face
  unlock, input hardening, process-local evidence, and failure-path tests.
