# Changelog

## 0.5.4 — 2026-09-14

- Run the newly staged, root-validated update transaction immediately so
  updater migrations take effect in one pass instead of the following update.

## 0.5.3 — 2026-09-14

- Preserve sudo's normal timestamp policy so multi-step workflows such as
  `omarchy-update` do not require a fresh face scan and approval for every
  privileged subprocess.
- Migrate existing installations transactionally and restore the prior policy
  if a plugin update fails.

## 0.5.2 — 2026-09-13

- Queue face-unlock requests made during the lock transition and begin scanning
  as soon as the compositor confirms the secure lock surface.
- Keep the queued scan visible and allow typing or cancellation to clear it.

## 0.5.1 — 2026-09-13

- Publish a root-owned, nonsecret status summary so the widget remains useful
  without exposing Howdy configuration or biometric vectors.
- Replace the multi-prompt updater with one fixed-purpose, root-owned update
  transaction and include PAM service files in update rollback.
- Make the native sudo fixture independent of temporary-disk capacity.
- Document the harmless OpenCV 5.0 graph-engine target warnings.

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
