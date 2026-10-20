# jupyter-kernel-client

`jk` is a command-line tool and Python library for **discovering, starting, using,
and gracefully stopping Jupyter kernels**. It works with existing Jupyter,
IPython, and Spyder sessions as well as detached kernels it starts itself.

It is designed for scripts and AI agents that need a **stable, machine-readable way to inspect or modify a live Python session**.

## Quick Start With Codex

This README describes the unreleased **`0.2.0.dev0` development version**.
Install it from GitHub, then install its user-level Codex skill:

```bash
pipx install git+https://github.com/hruskamiro/jupyter-kernel-client.git@main
jk skill install
```

Open the Jupyter, IPython, or Spyder session whose live state you want Codex to
use, then share its connection information in either of these ways:

- **Jupyter or IPython:** run `%connect_info` and copy its output.
- **Spyder:** install
  [`spyder-copy-current`](https://github.com/hruskamiro/spyder-copy-current) in
  the environment where Spyder runs, restart Spyder, and focus the intended
  IPython console. Press `Ctrl+Alt+K` once to copy the raw connection information,
  or twice quickly to copy a complete `jk`-ready agent prompt.

Paste the connection information or Spyder prompt into Codex and add the task:

```text
Use the $jk skill with this exact live Jupyter kernel. Inspect the existing
variables and determine which columns in df contain missing values.

<paste the connection information here>
```

Codex can now inspect and extend the state already loaded in that Python process.
The connection belongs to one kernel; copy fresh information after a restart.

## Intended Use Case

You are working in an IPython console, Spyder console, notebook kernel, or other Jupyter-backed Python session. **The session already has important state loaded:** imports, data frames, models, helper functions, configuration, intermediate results, and whatever else you have built up interactively.

**Instead of asking an AI agent to recreate that state from scratch, give it access to the existing kernel.** Export or copy the kernel connection information, tell the agent to use `jk`, and let it inspect variables, run experiments, evaluate expressions, and return structured output from the same live Python process you are using.

This is useful when the hard part is **not writing code from a blank environment**, but **exploring and manipulating the state that already exists in a live session**.

## Install

For the development features documented here, install GitHub `main`:

```bash
pipx install git+https://github.com/hruskamiro/jupyter-kernel-client.git@main
```

Published releases are available through `pipx install jupyter-kernel-cli`, but
the PyPI release does not yet include the bundled skill or the new kernel
lifecycle and process-discovery commands. Nothing from this development version
has been published to PyPI.

From a local checkout:

```bash
pipx install --force .
python -m pip install -e ".[dev]"
```

Check:

```bash
command -v jk
jk --help
```

`pipx` normally exposes the command on `PATH` from `$HOME/.local/bin/jk`. If
`command -v jk` finds nothing, run `pipx ensurepath`, start a new shell, and
check again.

### Install the Codex skill

Install the bundled `$jk` skill for the current Codex user:

```bash
jk skill install
```

The command installs to `$CODEX_HOME/skills/jk`, or `~/.codex/skills/jk` when
`CODEX_HOME` is unset. It does not store kernel connection information. Use
`jk skill path` to print the destination, and use `jk skill install --force` to
replace an installed copy whose contents differ.

The skill teaches Codex how to select the intended live kernel, prefer
structured output, work with persistent state, and handle timeouts without
accidentally repeating execution. Invoke it explicitly with `$jk`, or let Codex
select it when a request concerns a live Jupyter, IPython, or Spyder session.

### Upgrade

To move an existing installation to development `main`, reinstall from GitHub,
then refresh the installed skill. The skill's `--force` replaces local edits:

```bash
pipx install --force git+https://github.com/hruskamiro/jupyter-kernel-client.git@main
jk skill install --force
```

For an installation tracking PyPI releases instead, use
`pipx upgrade jupyter-kernel-cli`; this does not switch it to GitHub `main`.

## Usage

### Start and discover kernels

Start a detached kernel with the Python environment installed alongside `jk`,
or select an analysis environment explicitly:

```bash
jk kernel start --json
jk kernel start --python /path/to/env/bin/python --cwd /path/to/project --json
jk kernel start --connection-file /path/to/new/kernel.json --json
```

The selected Python must contain `ipykernel`. The command waits for readiness,
then returns the PID, connection-file `path`, log path, Python executable and
working directory. By default it creates a unique `kernel-*.json` in the standard
Jupyter runtime directory, with a sibling `.log`. Connection and log files are
private and existing files are never overwritten. Use `--log` and `--timeout`
to customize the log location and startup wait. Connection secrets are never
included in command output.

The kernel has detached standard streams and runs independently of the launching
CLI or terminal. It is not a service: machine shutdown, scheduler/job cleanup,
or other system policy can still stop it. Startup failure terminates only the
newly launched child, removes its new connection file, and retains its log.

`jk kernels` merges runtime-directory files with recognized Python ipykernel and
Spyder processes owned by the current user on the current machine. It also finds
processes using custom connection paths; there is no separate `jk` registry.
Forked workers with an ancestor using the same connection path are not additional
kernels. Process information may be incomplete because of access restrictions.

```bash
jk kernels --json
jk kernels --probe --json --limit 0
```

Each record has `path`, `file_exists`, discovery `sources`, process metadata,
`running`, and `responsive`. `running: true` means a matching process was seen;
`null` means unknown, not dead. `responsive` is only measured with `--probe`:
`false` can mean busy or unreachable, not necessarily dead. Probe failures are
reported in `error`. Live-process records appear first. Listing does not execute
kernel code, and no connection file is opened unless probing is requested.

### Stop a kernel

```bash
jk kernel stop -f /path/to/kernel.json --json
```

Stopping requires an explicit connection path; it never selects a kernel from
environment defaults. It requests graceful Jupyter shutdown without executing
user code or sending OS signals. If the local process is identifiable, it waits
for that process to exit. Otherwise a shutdown reply is reported as
`shutdown_acknowledged`, with `stopped: null`, not as a verified process exit.
Multiple matching processes cause refusal before sending the request.

Use `--timeout` to change the default 10-second wait. A timeout returns exit code
124 and does not imply the request was cancelled; it may still complete. There
is no automatic interrupt or force-kill. The command does not delete connection
files or logs (the kernel may remove its own connection file). Stop only kernels
you intend to shut down: their in-memory state is lost.

### Work with an existing kernel

Common commands:

```bash
jk kernels
jk kernels --probe
jk exec -f /path/to/kernel.json "x = 41"
jk eval -f /path/to/kernel.json "x + 1"
jk get -f /path/to/kernel.json x
jk vars -f /path/to/kernel.json --json
jk interrupt -f /path/to/kernel.json --json
jk demo -f /path/to/kernel.json --json
```

Use **JSON for agents** and stdin for larger generated code:

```bash
cat <<'PY' | jk exec -f /path/to/kernel.json --json --stdin
import pandas as pd

summary = {
    "variables": sorted(name for name in globals() if not name.startswith("_")),
    "answer": 6 * 7,
}
summary
PY
```

Other supported forms:

```bash
jk exec -f /path/to/kernel.json --file script.py
jk -f /path/to/kernel.json --json eval "x + 1"
export JK_CONNECTION_FILE=/path/to/kernel.json
jk eval "df.shape"
```

If execution times out, the code may still be running in the kernel. Send an
interrupt request separately:

```bash
jk exec -f /path/to/kernel.json --timeout 5 --json "long_running_call()"
jk interrupt -f /path/to/kernel.json --json
```

The JSON response includes status, stdout, stderr, rich display outputs, final `text/plain` result, parsed Python literal when possible, traceback details, elapsed time, timeout state, and message id.

## Using `jk` from Codex

Give Codex the **active kernel connection information** and tell it to use `jk`,
the locally installed **jupyter-kernel-client CLI**, to connect to that exact
kernel.

Codex should run kernel-facing `jk` commands **outside the command sandbox on
the first attempt**. This gives `jk` direct access to the local Jupyter kernel
sockets while the rest of the session remains workspace-sandboxed. A check such
as `command -v jk` can still run inside the sandbox.

You can copy the connection information from `%connect_info`. For integration
with the Spyder IDE, use
[`spyder-copy-current`](https://github.com/hruskamiro/spyder-copy-current) and
press `Ctrl+Alt+K` in Spyder to copy the current console's connection
information or a complete agent-ready prompt.

For example:

```text
Use the $jk skill to connect to this exact live Jupyter kernel. Inspect the
available variables, run small experiments there, and report the results.

<paste the kernel connection information here>
```

Useful checks if it does not work:

1. Resolve the installed executable with `command -v jk`. For a typical pipx
   install, also check `$HOME/.local/bin/jk`.
2. Pass the connection file explicitly with `jk -f /path/to/kernel.json ...`.
3. Make sure the installed `jk` environment has `jupyter-client`.

When the requested variable or expression is already known, Codex can call
`jk get` or `jk eval` directly. It only needs `jk vars` first when it must
discover what state is present. The kernel-facing command should go outside the
sandbox immediately rather than spending the readiness timeout on a sandboxed
attempt that cannot reach the local sockets.

**Approving `jk` allows arbitrary code execution in the connected Jupyter
kernel.** Treat this as execution access to that live Python session.

## Execution JSON Contract

Successful execution JSON responses include the following fields. Startup,
shutdown and discovery return the records described in their sections above.

```json
{
  "status": "ok",
  "ok": true,
  "execution_count": 12,
  "stdout": "",
  "stderr": "",
  "outputs": [],
  "result_text": "42",
  "result_python": 42,
  "ename": null,
  "evalue": null,
  "traceback": [],
  "elapsed_seconds": 0.01,
  "timed_out": false,
  "msg_id": "..."
}
```

Exit codes:

```text
0    operation succeeded (shutdown may be acknowledged without verified exit)
1    kernel execution raised an error
2    client or argument error
124  execution, interrupt-reply or shutdown-confirmation timeout
```

Execution timeouts only stop the client wait. Timed-out execution may continue in the
kernel until it finishes or is interrupted. `jk interrupt` sends a Jupyter
`interrupt_request` on the control channel; for Python kernels this is the
normal KeyboardInterrupt-style path. It is not a process kill, so native
extensions or blocking system calls may not stop immediately.

## Python API

```python
from jupyter_kernel_client import eval_expression, interrupt_kernel

response = eval_expression("/path/to/kernel.json", "x + 1")
if response.ok:
    print(response.result_python)

interrupt = interrupt_kernel("/path/to/kernel.json")
print(interrupt.status)
```

For an explicitly requested temporary kernel, the same lifecycle and discovery
operations are available as Python functions:

```python
from jupyter_kernel_client import discover_kernels, eval_expression, start_kernel, stop_kernel

kernel = start_kernel()  # Optional python=, cwd=, connection_file=, log= and timeout=.
try:
    response = eval_expression(kernel["path"], "sum(range(101))")
    print(response.result_python)
    print(discover_kernels())
finally:
    print(stop_kernel(kernel["path"]))  # Inspect status/stopped; a timeout is not a force-kill.
```

## License

MIT.
