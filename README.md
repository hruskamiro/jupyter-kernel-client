# jupyter-kernel-client

`jk` is a small command-line tool and Python library for executing code in an existing Jupyter kernel.

It is designed for scripts and AI agents that need a stable, machine-readable way to inspect or modify a live Python session.

## Install

Recommended for normal CLI use:

```bash
pipx install .
```

Upgrade after editing a local checkout:

```bash
pipx install --force .
```

For editable development:

```bash
python -m pip install -e ".[dev]"
```

Check the command:

```bash
jk --help
```

The repo also keeps a local `./jk` wrapper so the tool can be used before installation.

## Usage

List likely running kernels:

```bash
jk kernels
jk kernels --probe
jk kernels --json --probe
```

Execute code:

```bash
jk exec -f /path/to/kernel.json "x = 41"
jk eval -f /path/to/kernel.json "x + 1"
jk get -f /path/to/kernel.json x
jk vars -f /path/to/kernel.json --json
jk demo -f /path/to/kernel.json --json
```

The older option order is also accepted:

```bash
jk -f /path/to/kernel.json --json eval "x + 1"
```

Use JSON for agents:

```bash
jk exec -f /path/to/kernel.json --json "print('hello'); 2 + 2"
```

Read larger code from a file or stdin:

```bash
jk exec -f /path/to/kernel.json --file script.py
printf 'sum(range(10))\n' | jk exec -f /path/to/kernel.json --stdin
```

For a big agent-generated block, stdin is usually the cleanest interface:

```bash
cat <<'PY' | jk exec -f /path/to/kernel.json --stdin --json
import pandas as pd

summary = {
    "variables": sorted(name for name in globals() if not name.startswith("_")),
    "answer": 6 * 7,
}
summary
PY
```

The JSON response carries:

```text
status/result status, stdout, stderr, all rich display outputs, final text/plain result,
a parsed Python literal when text/plain is a literal, traceback details, elapsed time, and message id.
```

You can avoid repeating the connection file:

```bash
export JK_CONNECTION_FILE=/path/to/kernel.json
jk eval "df.shape"
```

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

## Development

```bash
python -m pip install -e ".[dev]"
python -m compileall src jk_client.py
python -m pip wheel . --no-deps -w dist
```

## License

MIT.
