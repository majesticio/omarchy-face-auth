# Marketplace submission draft

Title: `[Plugin]: Face Authentication`

### Repository URL

https://github.com/majesticio/omarchy-face-auth

### Category

System

### Tags

security, system, quickshell

### Suggest a missing tag

_No response_

### Maintainer notes

This plugin installs a commit-pinned howdy-next backend, checksum-pinned ONNX
models, and root-owned PAM,
sudo approval, polkit, and recovery components. It requires manual setup and
review. Sudo face evidence is bound to one process and one final command; the
approval overlay displays the resolved executable and arguments before sudo
continues. Screen unlock is immediate after a successful face scan. Password
fallback remains available.

Privileged installer inputs are copied to a private root-owned staging directory
and validated before execution. The lock clone has a recorded upstream hash,
reviewable patch, and rollback-safe resync workflow.

### Submission checklist

- [ ] The repository is public and contains installation and removal instructions.
- [ ] I have documented the plugin license and any external dependencies.
- [ ] I confirm that I own or have permission to submit this plugin and its preview assets.
- [ ] The plugin does not overwrite user configuration without explicit consent.
- [ ] I understand that approval is for listing and is not a security review.
