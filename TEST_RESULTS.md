# Automated Test Results

This file is the append-only, authoritative history of every automated test
run throughout the build. Starting with the next test prompt, append a dated
section for each test batch. Name the build prompt it covers, then record one
line per case using this exact format:

```text
Test <number>: <PASS|FAIL|MANUAL> — <what was tested>
```

For every `FAIL` or `MANUAL` entry, add an explanation underneath describing
what was expected, what happened, and, once fixed, what the fix was. Never
overwrite previous entries.