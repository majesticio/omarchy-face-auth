# Security model

This project adds convenience authentication to one local Omarchy account. Face
recognition is weaker than a password and does not provide Windows Hello-class
anti-spoofing. Use the password path for sensitive or unexpected requests.

## Trust boundaries

- Sudo policy remains authoritative. The approval plugin receives the resolved
  executable and argument vector from sudo after policy evaluation; neither the
  controller nor the dialog executes it.
- A face result is process-local, expires after 30 seconds, and is consumed by
  one sudo request. There is no reusable token, public approval socket, or sudo
  timestamp cache.
- The root controller accepts fixed modes only. It launches the UI as the active
  local user over an inherited socket and requires fresh password-only PAM for
  every profile or preference mutation.
- Settings, PAM configuration, Howdy configuration, models, and runtime locks
  must be bounded regular files owned by root and not writable by group or other.
  Symlinks and malformed metadata fail closed. The bar reads only a root-owned
  status summary; Howdy configuration and biometric vectors remain inaccessible.
- Privileged installation and updates execute only root-owned staged or already
  installed scripts. Every staged input is checked again before it is installed.
- howdy-next's small setuid helper stages only validated configuration and model
  inputs for the unprivileged recognition process; its pinned upstream test suite
  is run when the package is built.
- Screen unlock begins only after the compositor reports a secure session-lock
  surface. A successful screen scan unlocks directly; sudo always shows the
  command-specific approval overlay.

## Limits

The approval overlay is not a secure-attention key. Software already able to
control the desktop can interact with it, and a displayed script or shell can do
more after it starts. The IR recognizer can be susceptible to presentation
attacks. Startup login, disk unlock, remote sessions, and multi-user enrollment
are outside this installation's scope.

Passwords, face embeddings, camera frames, and command arguments are never
logged. The privileged controller disables core dumps before accepting approval
or management input. The repository excludes models, captures, build output,
downloaded archives, and package artifacts.
