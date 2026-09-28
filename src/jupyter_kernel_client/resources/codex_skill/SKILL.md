---
name: jk
description: Inspect and work with state in an existing live Jupyter, IPython, or Spyder kernel using the jk CLI. Use when the user supplies kernel connection information or asks to examine or modify variables in their active Python session.
---

# Work with a live Jupyter kernel

Use `jk` to work in the user's existing Jupyter-backed Python process. Treat the
kernel as a persistent, stateful environment and use the exact connection the
user supplied.

## Connect

Resolve the executable before first use with `command -v jk`. A pipx install
normally exposes it on `PATH`; if that lookup fails, check the common pipx
location `$HOME/.local/bin/jk`. Use the resolved executable consistently,
especially when requesting approval to run outside a sandbox.

Use the supplied connection-file path with `-f`. If only raw connection JSON is
available, write it unchanged to an owner-only temporary file, use it, and
remove it afterward. Never expose its connection key in the response.

Without a supplied connection, use `jk kernels --probe --json`. Use a discovered
kernel only when the intended one is unambiguous.

Local Jupyter connections use host sockets. In a Codex command sandbox, run the
required kernel-facing `jk` command outside the sandbox through the normal
approval flow on the first attempt. Do not probe the kernel from inside the
sandbox first. Executable discovery such as `command -v jk` can remain
sandboxed. If the outside-sandbox command does not respond, treat the supplied
connection as stale or unavailable; process listings inside the sandbox do not
establish whether the host kernel is alive. After a kernel restart, request new
connection information instead of reusing the stale file.

## Inspect and execute

Prefer structured output and use the narrowest operation. If the user names a
specific variable or expression, go directly to `get` or `eval`. Use `vars`
when the task requires discovering or orienting to existing state:

```text
jk vars -f /path/to/kernel.json --json --repr-length 120
jk get -f /path/to/kernel.json --json variable_name
jk eval -f /path/to/kernel.json --json "expression"
jk exec -f /path/to/kernel.json --json --stdin
```

- Use `get` for one compact object.
- Use `eval` for focused questions. Expressions can have side effects, so do not
  assume every `eval` is read-only.
- Use `exec` for multiline work and deliberate state changes, with stdin for
  generated code or `--file` for an existing file.

Keep large data frames and arrays in the kernel. Return shapes, columns, counts,
quantiles, small record samples, or grouped summaries instead of full
representations. Convert pandas and NumPy results to plain dictionaries, lists,
`int`, or `float` when needed for compact, unambiguous JSON.

## Manage persistent state

Before a new analysis branch, recheck important shapes, columns, and counts. Use
expected notebook names for intended results and descriptive names for derived
objects. Avoid arbitrary suffixes and accidental input overwrites.

Run state changes sequentially. Keep them focused enough to diagnose partial
completion, and return a compact summary from longer work. Do not run `jk demo`
unless asked; it creates kernel variables.

Report what was executed and what the kernel returned, without exposing the
connection secret.

## Save artifacts

Save plots and reports to explicit paths, return useful metadata, and verify
files on the shared filesystem when appropriate. Close Matplotlib figures and
save important outputs outside kernel globals.

Move accepted methodology into project source, configuration, and tests when the
task calls for it, then verify it from a clean process.

## Handle errors and timeouts

Use the JSON response fields to diagnose failures. A client timeout does not
mean execution stopped, so do not repeat timed-out code. If appropriate, send
`jk interrupt`, probe responsiveness with a small expression, and inspect
partial assignments before continuing. Give known long calculations realistic
timeouts, and do not submit competing work while the kernel is busy.

If an explicitly supplied kernel does not respond, report that connection
failure rather than switching to a different live kernel.
