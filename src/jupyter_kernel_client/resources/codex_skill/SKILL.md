---
name: jk
description: Discover and work with live Jupyter, IPython, or Spyder kernels using the jk CLI, or start and stop kernels when requested. Use when the user supplies kernel connection information or asks to work in a persistent Python session.
---

# Work with Jupyter kernels

Use `jk` to work in the user's existing Jupyter-backed Python process. Treat the
kernel as a persistent, stateful environment and use the exact connection the
user supplied.

Access to a kernel does not authorize starting, replacing, restarting,
interrupting, or shutting it down. Do not use lifecycle operations as implicit
recovery steps; obtain authorization for them.

## Connect

Resolve the executable before first use with `command -v jk`. A pipx install
normally exposes it on `PATH`; if that lookup fails, check the common pipx
location `$HOME/.local/bin/jk`. Use the resolved executable consistently,
especially when requesting approval to run outside a sandbox.

Use the supplied connection-file path with `-f`. If only raw connection JSON is
available, write it unchanged to an owner-only temporary file, use it, and
remove it afterward. Never expose its connection key in the response.

Without a supplied connection, list candidates with `jk kernels --json` and
probe relevant candidates when needed. Discovery merges runtime files with
current-user local Python kernel processes, including custom connection paths.
There is no separate registry. Stale files can remain and process inspection can
be incomplete. `running: true` means a process was seen; `null` means unknown.
`responsive` is only measured by `--probe`. Use a discovered kernel only when the
intended one is unambiguous; do not simply choose the newest file.

Local Jupyter connections use host sockets. In a Codex command sandbox, run the
required kernel-facing `jk` command outside the sandbox through the normal
approval flow on the first attempt. Do not probe the kernel from inside the
sandbox first. Executable discovery such as `command -v jk` can remain
sandboxed. A readiness timeout can mean the kernel is busy or unreachable, not
necessarily dead. Process listings inside the sandbox do not establish whether
the host kernel is alive. After a kernel restart, request new connection
information instead of reusing the stale file.

Establish the kernel's host, working directory, Python executable, and relevant
loaded state once, then reuse that context until it changes or results conflict.
Run `jk` where the kernel's sockets are reachable, using the project's remote
execution workflow when applicable. A local connection-file path alone does not
make remote loopback ports reachable. Changing the CLI's working directory or
Python environment does not change those of the already-running kernel.

## Start a kernel when requested

Use `jk kernel start --json` instead of improvising shell detachment. It defaults
to the Python environment containing `jk`; use `--python /path/to/env/bin/python`
when the task needs another environment, and `--cwd /path/to/project` for its
working directory. That interpreter must contain `ipykernel`.

The command detaches, waits for readiness, and returns the PID, connection `path`,
and log path. Reuse that exact path for later calls. Default connection files
are unique files in the Jupyter runtime directory; `--connection-file` and
`--log` select new explicit paths without overwriting existing files. Startup
failure stops only the new child and preserves its log. A detached kernel
survives CLI exit but not necessarily host shutdown or system job cleanup.

If the surrounding command runner times out before reporting the result,
discover the attempted kernel and check its state before starting another.

## Stop a kernel when authorized

Use `jk kernel stop -f /path/to/kernel.json --json` for graceful shutdown instead
of improvising client code or OS signals. An explicit connection path is required;
reuse the path of the exact kernel the user authorized you to stop. Its in-memory
state will be lost. Stopping a kernel you created also requires authorization,
such as an explicit request to clean up a temporary test kernel.

`status: stopped` confirms the identified local process exited.
`shutdown_acknowledged` with `stopped: null` means the server acknowledged the
request but a local process could not be identified. A timeout does not cancel
the request and never triggers an automatic interrupt or force-kill. Do not
claim shutdown was verified if only an acknowledgement or timeout was returned.
The command does not delete connection files or logs.

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

Prefer stdin or a code file to fragile multiline shell quoting. With a remote
shell, account for both quoting layers; JSON encoding is not shell escaping.

Keep large data frames and arrays in the kernel. Return shapes, columns, counts,
quantiles, small record samples, or grouped summaries instead of full
representations. Convert pandas and NumPy results to plain dictionaries, lists,
`int`, or `float` when needed for compact, unambiguous JSON.

## Manage persistent state

Before a new analysis branch, recheck important shapes, columns, and counts. Use
expected notebook names for intended results and descriptive names for derived
objects. Avoid arbitrary suffixes and accidental input overwrites.

Reuse expensive loaded inputs and keep experimental results separate. Do not
clear the namespace or reload large inputs merely to reproduce the environment.
After source changes, reload only the relevant modules and recreate dependent
objects deliberately: existing instances and `from module import name` bindings
do not automatically acquire the revised implementation.

Avoid concurrent execution against one kernel. Keep state changes focused enough
to diagnose partial completion, and return a compact summary from longer work.
Do not run `jk demo` unless asked; it creates kernel variables.

Report what was executed and what the kernel returned, without exposing the
connection secret.

## Save artifacts

Save plots and reports to explicit paths, return useful metadata, and verify
files on the shared filesystem when appropriate. Close Matplotlib figures and
save important outputs outside kernel globals.

Move accepted methodology into project source, configuration, and tests when the
task calls for it, then verify it from a clean process.

## Handle errors and timeouts

Inspect `status`, `ok`, `timed_out`, and error fields in JSON responses; receiving
JSON does not itself mean the operation succeeded. A client timeout does not mean
execution stopped or changes were rolled back, so do not blindly repeat the
code or enqueue another execution to check whether it finished. Check available
status or output first; if completion remains uncertain, report that uncertainty.
Use `jk interrupt` only when authorized. Once the kernel is responsive again,
inspect partial assignments before continuing. Give known long calculations
realistic timeouts and avoid competing work while the kernel is busy.

If an explicitly supplied kernel does not respond, report that connection
failure rather than switching to a different live kernel.
