---
name: Lab upload security
description: Keep private lab-result files addressable only by generated basenames and directory-descriptor operations.
---

Private lab-result storage and delivery must use generated basenames, directory
file descriptors, and no-follow flags for create/read/delete operations. Do not
pass user filenames or joined user-controlled paths directly to filesystem
helpers or response classes.

**Why:** Path-taint scanners do not reliably infer safety from a later
`resolve().relative_to()` check, and uploaded clinical documents require
defense in depth against traversal and symlink attacks.

**How to apply:** Preserve original upload names only as display metadata;
never use them as storage paths or download header values. Keep containment
tests for legacy records and descriptor-based operations for new code.