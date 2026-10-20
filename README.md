# jupyter-kernel-client

`jk` is a small command-line tool and Python library for **executing code in an existing Jupyter kernel**.

It is designed for scripts and AI agents that need a **stable, machine-readable way to inspect or modify a live Python session**.

## Quick Start With Codex

Install the CLI and its user-level Codex skill:

```bash
pipx install jupyter-kernel-cli
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

Recommended:

```bash
pipx install jupyter-kernel-cli
```

Other install paths:

```bash
pipx install git+https://github.com/hruskamiro/jupyter-kernel-client.git
pipx upgrade jupyter-kernel-cli
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

Upgrade the CLI, then refresh the installed skill from the new package:

```bash
pipx upgrade jupyter-kernel-cli
jk skill install --force
```

## Usage

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

## JSON Contract

Successful JSON responses include:

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
0    kernel execution succeeded
1    kernel execution raised an error
2    client or argument error
124  client timed out waiting for the kernel or interrupt reply
```

Timeouts only stop the client wait. Timed-out execution may continue in the
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

## License

MIT.
