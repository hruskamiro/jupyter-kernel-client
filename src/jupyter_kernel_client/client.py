from __future__ import annotations

import ast
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty
from typing import Any, Dict, List, Optional

from jupyter_client import BlockingKernelClient


class KernelClientError(RuntimeError):
    """Raised when the client cannot complete a request."""


@dataclass
class RichOutput:
    output_type: str
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    transient: Dict[str, Any] = field(default_factory=dict)
    execution_count: Optional[int] = None
    text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "output_type": self.output_type,
            "data": self.data,
            "metadata": self.metadata,
            "transient": self.transient,
            "execution_count": self.execution_count,
            "text": self.text,
        }


@dataclass
class KernelResponse:
    status: str
    execution_count: Optional[int]
    stdout: str
    stderr: str
    outputs: List[RichOutput]
    result_text: Optional[str]
    result_python: Any
    ename: Optional[str]
    evalue: Optional[str]
    traceback: List[str]
    elapsed_seconds: float
    timed_out: bool
    msg_id: str

    @property
    def ok(self) -> bool:
        return self.status == "ok" and not self.timed_out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "ok": self.ok,
            "execution_count": self.execution_count,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "outputs": [output.to_dict() for output in self.outputs],
            "result_text": self.result_text,
            "result_python": self.result_python,
            "ename": self.ename,
            "evalue": self.evalue,
            "traceback": self.traceback,
            "elapsed_seconds": self.elapsed_seconds,
            "timed_out": self.timed_out,
            "msg_id": self.msg_id,
        }


def _parse_python_literal(text: Optional[str]) -> Any:
    if text is None:
        return None
    try:
        return ast.literal_eval(text)
    except Exception:
        return text


def _make_client(connection_file: str, *, ready_timeout: float = 5.0) -> BlockingKernelClient:
    path = Path(connection_file).expanduser()
    if not path.exists():
        raise KernelClientError(f"Connection file does not exist: {path}")

    client = BlockingKernelClient(connection_file=str(path))
    client.load_connection_file()
    client.start_channels()
    try:
        client.wait_for_ready(timeout=ready_timeout)
    except Exception as exc:
        client.stop_channels()
        raise KernelClientError(f"Kernel did not become ready within {ready_timeout:.1f}s: {exc}") from exc
    return client


def kernel_is_ready(connection_file: str, *, timeout: float = 1.0) -> None:
    """Raise KernelClientError if the kernel connection file does not respond."""
    client = _make_client(connection_file, ready_timeout=timeout)
    client.stop_channels()


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


def _message_output(msg_type: str, content: Dict[str, Any]) -> Optional[RichOutput]:
    if msg_type not in {"execute_result", "display_data", "update_display_data"}:
        return None

    data = {key: _json_safe(value) for key, value in content.get("data", {}).items()}
    text = data.get("text/plain")
    return RichOutput(
        output_type=msg_type,
        data=data,
        metadata=content.get("metadata", {}),
        transient=content.get("transient", {}),
        execution_count=content.get("execution_count"),
        text=text if isinstance(text, str) else None,
    )


def execute(
    connection_file: str,
    code: str,
    *,
    timeout: float = 30.0,
    ready_timeout: float = 5.0,
    silent: bool = False,
    store_history: bool = True,
    allow_stdin: bool = False,
) -> KernelResponse:
    """Execute code in an existing Jupyter kernel and collect its IOPub output."""
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")

    client = _make_client(connection_file, ready_timeout=ready_timeout)
    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []
    outputs: List[RichOutput] = []
    result_text: Optional[str] = None
    execution_count: Optional[int] = None
    status = "unknown"
    ename: Optional[str] = None
    evalue: Optional[str] = None
    traceback: List[str] = []
    msg_id = ""
    started = time.monotonic()
    timed_out = False

    try:
        msg_id = client.execute(
            code,
            silent=silent,
            store_history=store_history,
            user_expressions={},
            allow_stdin=allow_stdin,
            stop_on_error=True,
        )
        deadline = started + timeout

        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            try:
                msg = client.get_iopub_msg(timeout=remaining)
            except Empty:
                continue

            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                continue

            msg_type = msg.get("msg_type")
            content = msg.get("content", {})

            if msg_type == "stream":
                if content.get("name") == "stderr":
                    stderr_chunks.append(content.get("text", ""))
                else:
                    stdout_chunks.append(content.get("text", ""))
            elif msg_type in {"execute_result", "display_data", "update_display_data"}:
                output = _message_output(msg_type, content)
                if output is not None:
                    outputs.append(output)
                    if output.text is not None:
                        result_text = output.text
                    execution_count = output.execution_count or execution_count
            elif msg_type == "error":
                status = "error"
                ename = content.get("ename")
                evalue = content.get("evalue")
                traceback = content.get("traceback", [])
            elif msg_type == "execute_input":
                execution_count = content.get("execution_count", execution_count)
            elif msg_type == "status" and content.get("execution_state") == "idle":
                if status != "error":
                    status = "ok"
                break

        timed_out = status == "unknown"
        if timed_out:
            status = "timeout"
    finally:
        client.stop_channels()

    return KernelResponse(
        status=status,
        execution_count=execution_count,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
        outputs=outputs,
        result_text=result_text,
        result_python=_parse_python_literal(result_text),
        ename=ename,
        evalue=evalue,
        traceback=traceback,
        elapsed_seconds=round(time.monotonic() - started, 6),
        timed_out=timed_out,
        msg_id=msg_id,
    )


def eval_expression(connection_file: str, expression: str, *, timeout: float = 30.0) -> KernelResponse:
    sentinel = f"__jk_value_{uuid.uuid4().hex}__"
    code = f"globals()[{sentinel!r}] = ({expression})\nglobals().pop({sentinel!r})"
    return execute(connection_file, code, timeout=timeout)


def get_variable(connection_file: str, variable_name: str, *, timeout: float = 30.0) -> KernelResponse:
    return eval_expression(connection_file, variable_name, timeout=timeout)
