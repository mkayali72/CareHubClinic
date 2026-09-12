---
name: Report export dependencies
description: Portable installation fallback for Python PDF and XLSX export libraries in this workspace.
---

When adding Python dependencies to this project, the package-management callback
may fail because the system Python is externally managed and has no writable
pip target. Install resolved packages into the project `.pythonlibs` site-packages
with `uv`, and keep pinned versions in `requirements.txt` so Docker and other
portable environments remain reproducible.

**Why:** The application intentionally avoids Replit-specific runtime
dependencies, but the workspace's immutable Nix Python cannot always accept a
normal pip install.

**How to apply:** Prefer the package-management flow first; if it reports the
externally-managed-environment error, use the writable project target rather
than modifying the Nix store or bypassing the environment guard.