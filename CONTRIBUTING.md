# Contributing

Open an issue before changing PAM, sudo, polkit, enrollment, or recovery behavior.
Authentication changes must keep password fallback, fail closed on missing native
components, avoid public approval tokens or sockets, and include a test for the
relevant failure path.

Run `./scripts/check` before submitting a pull request. Do not include face models,
camera captures, downloaded archives, built packages, or machine-specific paths.
