"""Portable detached kernel launch and local discovery, without a registry."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from queue import Empty
import re
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from typing import Optional

import psutil
from jupyter_client import BlockingKernelClient
from jupyter_core.paths import jupyter_runtime_dir

from .client import KernelClientError, kernel_is_ready


def start_kernel(
    *, python: Optional[str] = None, connection_file: Optional[str] = None,
    cwd: Optional[str] = None, log: Optional[str] = None, timeout: float = 30.0,
) -> dict:
    """Start a detached ipykernel and return its PID and paths after readiness.

    Existing connection/log files are never overwritten. Failed startup stops
    only this new child and removes its connection file; its log is retained.
    The selected interpreter must contain ipykernel. No kernel code is executed.
    """
    _check_timeout(timeout)
    interpreter = os.path.expanduser(python or sys.executable)
    interpreter = shutil.which(interpreter) or str(Path(interpreter).resolve())
    directory = Path(cwd or Path.cwd()).expanduser().resolve()
    if not directory.is_dir():
        raise KernelClientError(f"Not a working directory: {directory}")
    path = (Path(connection_file).expanduser() if connection_file else
            Path(jupyter_runtime_dir()) / f"kernel-{uuid.uuid4().hex}.json").resolve()
    log_path = Path(log).expanduser().resolve() if log else path.with_suffix(".log")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Reserve with O_EXCL, including against dangling symlinks. A valid initial
    # connection file lets ipykernel select its ports and rewrite it securely.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    process = None
    try:
        with os.fdopen(fd, "w") as connection:
            config = {name + "_port": 0 for name in ("shell", "iopub", "stdin", "hb", "control")}
            config.update(ip="127.0.0.1", transport="tcp", key=secrets.token_hex(32),
                          signature_scheme="hmac-sha256")
            json.dump(config, connection)
        log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        log_fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        environment = os.environ.copy()
        # A new independent kernel must not inherit another kernel's parent poller.
        environment.pop("JPY_PARENT_PID", None)
        environment.pop("JPY_INTERRUPT_EVENT", None)
        detach = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
                  if os.name == "nt" else {"start_new_session": True})
        with os.fdopen(log_fd, "wb") as output:
            process = subprocess.Popen(
                [interpreter, "-m", "ipykernel_launcher", "-f", str(path)],
                cwd=str(directory), env=environment, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, close_fds=True, **detach,
            )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise KernelClientError(f"Kernel exited with code {process.returncode}")
            try:
                kernel_is_ready(str(path), timeout=min(0.5, deadline - time.monotonic()))
            except Exception:
                continue
            if process.poll() is None:
                return {"status": "ok", "ok": True, "pid": process.pid,
                        "path": str(path), "log": str(log_path), "python": interpreter,
                        "cwd": str(directory), "running": True, "responsive": True}
        raise KernelClientError(f"Kernel did not become ready within {timeout:g}s")
    except BaseException as exc:
        if process is not None:
            _stop_new_child(process)
        path.unlink(missing_ok=True)
        if isinstance(exc, Exception):
            raise KernelClientError(f"{exc}. Startup failed; see log: {log_path}") from exc
        raise


def stop_kernel(connection_file: str, *, timeout: float = 10.0) -> dict:
    """Request graceful shutdown; verify a matched local process exits.

    No signals, force-kill, readiness probes, or file deletion. If process
    inspection cannot identify the target, an acknowledgement is reported as
    such, not as a verified exit. A timeout does not undo the shutdown request.
    """
    _check_timeout(timeout)
    path = Path(connection_file).expanduser().resolve()
    if not path.is_file():
        raise KernelClientError(f"Connection file does not exist: {path}")
    matches = [record for record in _kernel_processes() if record["path"] == str(path)]
    if len(matches) > 1:
        raise KernelClientError(f"Multiple kernel processes use {path}; refusing ambiguous shutdown")
    process = psutil.Process(matches[0]["pid"]) if matches else None
    if process is not None and process.create_time() != matches[0]["created"]:
        raise KernelClientError("Kernel process changed during discovery; no shutdown request sent")
    client = BlockingKernelClient(connection_file=str(path))
    client.load_connection_file()
    started = time.monotonic()
    deadline = started + timeout
    acknowledged, stopped = False, None
    try:
        # Only the control channel is needed. In particular, do not start a
        # heartbeat thread that could race with immediate channel teardown.
        client.start_channels(shell=False, iopub=False, stdin=False, hb=False, control=True)
        msg_id = client.shutdown(restart=False)
        while time.monotonic() < deadline:
            stopped = _process_stopped(process) if process is not None else None
            if stopped is True or (acknowledged and process is None):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if acknowledged:
                time.sleep(min(0.05, remaining))
                continue
            try:
                reply = client.get_control_msg(timeout=min(0.1, remaining))
            except Empty:
                continue
            if (reply.get("msg_type") == "shutdown_reply" and
                    reply.get("parent_header", {}).get("msg_id") == msg_id):
                if reply.get("content", {}).get("status") == "error":
                    raise KernelClientError("Kernel rejected the shutdown request")
                acknowledged = True
        stopped = _process_stopped(process) if process is not None else None
    finally:
        client.stop_channels()
    complete = stopped is True or (acknowledged and process is None)
    status = "stopped" if stopped is True else "shutdown_acknowledged" if complete else "timeout"
    return {"status": status, "ok": complete, "path": str(path),
            "pid": process.pid if process is not None else None, "stopped": stopped,
            "shutdown_acknowledged": acknowledged, "timed_out": not complete,
            "elapsed_seconds": round(time.monotonic() - started, 6)}


def discover_kernels(*, limit: int = 20, probe: bool = False, timeout: float = 1.0) -> list:
    """Merge current-user local kernel processes with runtime connection files.

    running=True means a matching process was observed; None means unknown,
    not dead. responsive is only measured with probe=True. No connection keys,
    command-line dumps, or kernel code are returned.
    """
    if limit < 0:
        raise ValueError("limit must be nonnegative (0 means unlimited)")
    _check_timeout(timeout)
    records = {}
    runtime = Path(jupyter_runtime_dir()).expanduser()
    for path in runtime.glob("kernel-*.json"):
        try:
            records[str(path.resolve())] = _file_record(path.resolve(), "runtime")
        except OSError:
            continue
    for process in _kernel_processes():
        path = process.pop("path")
        key = path or f"pid:{process['pid']}"
        if key not in records:
            records[key] = _file_record(Path(path), "process") if path else {
                "path": None, "modified": None, "file_exists": None,
                "sources": ["process"], "processes": [], "running": None,
                "responsive": None, "error": None,
            }
        record = records[key]
        if "process" not in record["sources"]:
            record["sources"].append("process")
        record["processes"].append(process)
        record["running"] = True
    result = sorted(records.values(), key=lambda record: (
        record["running"] is True,
        max([record["modified"] or 0] + [p["created"] or 0 for p in record["processes"]]),
    ), reverse=True)
    if limit:
        result = result[:limit]
    if probe:
        for record in result:
            if not record["path"] or record["file_exists"] is not True:
                record["error"] = "Connection file unavailable; cannot probe"
                continue
            try:
                kernel_is_ready(record["path"], timeout=timeout)
                record["responsive"] = True
            except Exception as exc:
                record["responsive"] = False
                record["error"] = str(exc)
    return result


def _kernel_launch(argv):
    if not argv or not re.fullmatch(r"pythonw?(?:\d+(?:\.\d+)*)?(?:\.exe)?", Path(argv[0]).name, re.I):
        return None
    modules = {"ipykernel_launcher", "ipykernel", "ipykernel.kernelapp", "spyder_kernels.console"}
    kind = None
    for index, arg in enumerate(argv[1:], 1):
        if arg in ("-c", "-"):
            return None
        if arg == "-m":
            if index + 1 < len(argv) and argv[index + 1] in modules:
                kind = argv[index + 1]
            break
        if not arg.startswith("-"):
            if Path(arg).name == "ipykernel_launcher.py":
                kind = "ipykernel_launcher"
            break
    if kind is None:
        return None
    flags = {"-f", "--f", "--connection-file", "--IPKernelApp.connection_file"}
    path = None
    for index, arg in enumerate(argv):
        if arg in flags and index + 1 < len(argv):
            path = argv[index + 1]
        elif "=" in arg and arg.split("=", 1)[0] in flags:
            path = arg.split("=", 1)[1]
    return kind, path


def _kernel_processes():
    candidates, parents = {}, {}
    username = psutil.Process().username()
    for process in psutil.process_iter():
        try:
            with process.oneshot():
                if process.username() != username:
                    continue
                parents[process.pid] = process.ppid()
                launch = _kernel_launch(process.cmdline())
                if launch is None or process.status() == psutil.STATUS_ZOMBIE:
                    continue
                info = process.as_dict(attrs=["pid", "ppid", "cwd", "exe", "create_time"], ad_value=None)
                kind, path = launch
                if path:
                    path = Path(path).expanduser()
                    if not path.is_absolute():
                        path = Path(info["cwd"]) / path if info["cwd"] else None
                    path = str(path.resolve()) if path else None
                candidates[process.pid] = {
                    "pid": info["pid"], "ppid": info["ppid"], "kind": kind,
                    "cwd": info["cwd"], "python": info["exe"],
                    "created": info["create_time"], "path": path,
                }
        except (psutil.Error, OSError):
            continue
    # Fork workers inherit argv. An ancestor with the same connection path
    # identifies them as workers rather than additional kernels.
    for pid, candidate in candidates.items():
        ancestor, seen = parents.get(pid), {pid}
        while candidate["path"] and ancestor in parents and ancestor not in seen:
            seen.add(ancestor)
            if ancestor in candidates and candidates[ancestor]["path"] == candidate["path"]:
                break
            ancestor = parents[ancestor]
        else:
            yield candidate


def _file_record(path, source):
    try:
        stat = path.stat()
        modified, exists = stat.st_mtime, path.is_file()
    except FileNotFoundError:
        modified, exists = None, False
    except OSError:
        modified, exists = None, None
    return {"path": str(path), "modified": modified, "file_exists": exists,
            "sources": [source], "processes": [], "running": None,
            "responsive": None, "error": None}


def _check_timeout(timeout):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")


def _process_stopped(process):
    try:
        return not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True
    except psutil.AccessDenied:
        return None


def _stop_new_child(process):
    if process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
