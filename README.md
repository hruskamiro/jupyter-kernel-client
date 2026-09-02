# jupyter-kernel-client

`jk` is a small command-line tool and Python library for **executing code in an existing Jupyter kernel**.

It is designed for scripts and AI agents that need a **stable, machine-readable way to inspect or modify a live Python session**.

## Intended Use Case

You are working in an IPython console, Spyder console, notebook kernel, or other Jupyter-backed Python session. **The session already has important state loaded:** imports, data frames, models, helper functions, configuration, intermediate results, and whatever else you have built up interactively.

**Instead of asking an AI agent to recreate that state from scratch, give it access to the existing kernel.** Export or copy the kernel connection information, tell the agent to use `jk`, and let it inspect variables, run experiments, evaluate expressions, and return structured output from the same live Python process you are using.

The workflow is:

1. **Work normally** in an IPython, Spyder, notebook, or other Jupyter-backed console.
2. **Load the state you care about:** data, objects, functions, imports, models, and intermediate results.
3. **Copy the active kernel connection info**, for example with `%connect_info`.
4. **Give that connection info to Codex or another agent.**
5. **Tell the agent to use `jk`** to connect to that exact kernel.
6. **Let the agent inspect and experiment** with `jk exec`, `jk eval`, `jk get`, and `jk vars`.

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
jk --help
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

The JSON response includes status, stdout, stderr, rich display outputs, final `text/plain` result, parsed Python literal when possible, traceback details, elapsed time, timeout state, and message id.

## Using `jk` from Codex

Give Codex the **active kernel connection information** and tell it to use `jk`,
the locally installed **jupyter-kernel-client CLI**, to connect to that exact
kernel.

For Codex, the clearest instruction is usually to run `jk` **outside the command
sandbox**. This gives `jk` direct access to the local Jupyter kernel sockets
while the rest of the session can remain workspace-sandboxed.

You can copy the connection information from `%connect_info`. For integration
with the Spyder IDE, use
[`spyder-copy-current`](https://github.com/hruskamiro/spyder-copy-current) and
press `Ctrl+Alt+K` in Spyder to copy the current console's connection
information or a complete agent-ready prompt.

For example:

```text
Connect to this exact Jupyter kernel using jk, the locally installed
jupyter-kernel-client CLI. Run jk outside the command sandbox if approval is
needed. Inspect the available variables, run small experiments there, and report
the results.

<paste the kernel connection information here>
```

Useful checks if it does not work:

1. Make sure `jk` is installed and visible with `command -v jk`.
2. Pass the connection file explicitly with `jk -f /path/to/kernel.json ...`.
3. Make sure the installed `jk` environment has `jupyter-client`.

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
124  client timed out waiting for the kernel
```

Timeouts only stop the client wait. With only a connection file, `jk` cannot reliably kill or interrupt an arbitrary kernel process, so timed-out execution may continue in the kernel.

## Python API

```python
from jupyter_kernel_client import execute, eval_expression, get_variable

response = eval_expression("/path/to/kernel.json", "x + 1")
if response.ok:
    print(response.result_python)
```

## License

MIT.
