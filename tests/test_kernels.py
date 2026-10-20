"""Portable discovery and real detached-launch tests; only test kernels are stopped."""

import contextlib
import io
import json
import os
from pathlib import Path
from queue import Empty
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import psutil

from jupyter_kernel_client import kernels
from jupyter_kernel_client.cli import main
from jupyter_kernel_client.client import KernelClientError, eval_expression


class DiscoveryTests(unittest.TestCase):
    def test_only_real_python_kernel_launches_match(self):
        self.assertEqual(kernels._kernel_launch([
            "/env/python3.8", "-m", "ipykernel_launcher", "-f", "/tmp/custom.json",
        ]), ("ipykernel_launcher", "/tmp/custom.json"))
        self.assertEqual(kernels._kernel_launch([
            "python", "-m", "spyder_kernels.console", "--f=/tmp/custom.json",
        ]), ("spyder_kernels.console", "/tmp/custom.json"))
        for argv in (
            ["bash", "-c", "python -m ipykernel_launcher -f /tmp/custom.json"],
            ["tmux", "new-session", "python -m ipykernel_launcher"],
            ["python", "-c", "print('ipykernel_launcher')"],
            ["python", "other.py", "-m", "ipykernel_launcher"],
            ["python", "-m", "jupyter_kernel_client.cli", "kernels"],
        ):
            self.assertIsNone(kernels._kernel_launch(argv))

    def test_merges_sources_and_finds_custom_paths_without_reading_keys(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = Path(root) / "runtime"
            runtime.mkdir()
            standard = runtime / "kernel-test.json"
            custom = Path(root) / "custom.json"
            standard.write_text("not JSON; listing must not read it")
            custom.write_text("not JSON either")
            processes = [dict(pid=1, path=str(standard), created=1),
                         dict(pid=2, path=str(custom), created=2)]
            with patch.object(kernels, "jupyter_runtime_dir", return_value=str(runtime)), \
                    patch.object(kernels, "_kernel_processes", return_value=iter(processes)), \
                    patch.object(kernels, "kernel_is_ready") as probe:
                records = kernels.discover_kernels(limit=0)
            self.assertEqual(len(records), 2)
            by_path = {record["path"]: record for record in records}
            self.assertEqual(by_path[str(standard)]["sources"], ["runtime", "process"])
            self.assertEqual(by_path[str(custom)]["sources"], ["process"])
            self.assertTrue(all(record["running"] for record in records))
            self.assertTrue(all(record["responsive"] is None for record in records))
            probe.assert_not_called()

    def test_file_only_does_not_mean_dead_and_probe_does_not_change_running(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "kernel-stale.json"
            path.write_text("{}")
            with patch.object(kernels, "jupyter_runtime_dir", return_value=root), \
                    patch.object(kernels, "_kernel_processes", return_value=[]), \
                    patch.object(kernels, "kernel_is_ready", side_effect=KernelClientError("busy")):
                record, = kernels.discover_kernels(probe=True)
            self.assertIsNone(record["running"])
            self.assertFalse(record["responsive"])
            self.assertEqual(record["error"], "busy")

    def test_fork_workers_are_collapsed_but_distinct_child_kernels_remain(self):
        class Process:
            def __init__(self, pid, ppid, path):
                self.pid, self.parent, self.path = pid, ppid, path

            def username(self):
                return "test-user"

            def oneshot(self):
                return contextlib.nullcontext()

            def ppid(self):
                return self.parent

            def cmdline(self):
                return ["python", "-m", "ipykernel_launcher", "-f", self.path]

            def status(self):
                return psutil.STATUS_SLEEPING

            def as_dict(self, **kwargs):
                return dict(pid=self.pid, ppid=self.parent, cwd="/tmp", exe="/env/python", create_time=1)

        processes = [Process(1, 0, "kernel-a.json"), Process(2, 1, "kernel-a.json"),
                     Process(3, 2, "kernel-b.json")]
        with patch.object(kernels.psutil, "Process", return_value=processes[0]), \
                patch.object(kernels.psutil, "process_iter", return_value=processes):
            records = list(kernels._kernel_processes())
        self.assertEqual([record["pid"] for record in records], [1, 3])
        self.assertEqual(records[0]["path"], "/tmp/kernel-a.json")

    def test_permission_denied_process_is_skipped(self):
        process = unittest.mock.Mock()
        process.oneshot.side_effect = psutil.AccessDenied()
        with patch.object(kernels.psutil, "process_iter", return_value=[process]):
            self.assertEqual(list(kernels._kernel_processes()), [])


class StartTests(unittest.TestCase):
    def test_existing_paths_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "connection.json"
            path.write_text("keep")
            with self.assertRaises(FileExistsError):
                kernels.start_kernel(connection_file=str(path))
            self.assertEqual(path.read_text(), "keep")
            path.unlink()
            log = path.with_suffix(".log")
            log.write_text("keep log")
            with self.assertRaises(KernelClientError):
                kernels.start_kernel(connection_file=str(path))
            self.assertEqual(log.read_text(), "keep log")
            self.assertFalse(path.exists())

    def test_spawn_failure_cleans_only_new_connection_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "connection.json"
            with self.assertRaisesRegex(KernelClientError, "Startup failed"):
                kernels.start_kernel(python=str(Path(root) / "no-python"), connection_file=str(path))
            self.assertFalse(path.exists())
            self.assertTrue(path.with_suffix(".log").exists())

    def test_timeout_stops_only_the_new_child(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "connection.json"
            process = unittest.mock.Mock()
            process.poll.return_value = None
            with patch.object(kernels.subprocess, "Popen", return_value=process), \
                    patch.object(kernels, "kernel_is_ready", side_effect=KernelClientError("busy")):
                with self.assertRaisesRegex(KernelClientError, "did not become ready"):
                    kernels.start_kernel(connection_file=str(path), timeout=0.01)
            process.terminate.assert_called_once()
            process.wait.assert_called_once()
            self.assertFalse(path.exists())

    def test_invalid_inputs_fail_before_spawning(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                kernels.start_kernel(timeout=value)
        with self.assertRaises(ValueError):
            kernels.discover_kernels(limit=-1)

    def test_cli_dispatches_start(self):
        record = dict(pid=123, path="/tmp/kernel.json", log="/tmp/kernel.log")
        with patch("jupyter_kernel_client.cli.start_kernel", return_value=record) as start, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["kernel", "start", "--python", "/env/python", "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue()), record)
        self.assertEqual(start.call_args.kwargs["python"], "/env/python")


class DetachedIntegrationTests(unittest.TestCase):
    def test_start_calculate_and_graceful_stop_cli(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "stop-test.json"
            prefix = [sys.executable, "-m", "jupyter_kernel_client.cli"]
            start = subprocess.run(prefix + ["kernel", "start", "-f", str(path), "--json"],
                                   capture_output=True, text=True, timeout=45)
            self.assertEqual(start.returncode, 0, start.stderr + start.stdout)
            record = json.loads(start.stdout)
            process = psutil.Process(record["pid"])
            try:
                response = eval_expression(str(path), "sum(n * n for n in range(1, 101))", timeout=10)
                self.assertEqual(response.result_python, 338350)
                stop = subprocess.run(prefix + ["kernel", "stop", "-f", str(path), "--json"],
                                      capture_output=True, text=True, timeout=20)
                self.assertEqual(stop.returncode, 0, stop.stderr + stop.stdout)
                stopped = json.loads(stop.stdout)
                self.assertEqual(stopped["status"], "stopped")
                self.assertTrue(stopped["stopped"])
                self.assertEqual(stopped["pid"], record["pid"])
                self.assertFalse(stopped["timed_out"])
                self.assertEqual(stop.stderr, "")
                self.assertTrue(kernels._process_stopped(process))
                self.assertTrue(path.with_suffix(".log").is_file())
            finally:
                if kernels._process_stopped(process) is not True:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)

    def test_default_runtime_path_is_discoverable(self):
        with tempfile.TemporaryDirectory() as root:
            environment = dict(os.environ, JUPYTER_RUNTIME_DIR=root)
            command = [sys.executable, "-m", "jupyter_kernel_client.cli", "kernel", "start", "--json"]
            result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            record = json.loads(result.stdout)
            process = psutil.Process(record["pid"])
            try:
                path = Path(record["path"])
                self.assertEqual(path.parent, Path(root))
                self.assertTrue(path.name.startswith("kernel-"))
                self.assertEqual(record["log"], str(path.with_suffix(".log")))
                with patch.object(kernels, "jupyter_runtime_dir", return_value=root):
                    records = kernels.discover_kernels(limit=0)
                match, = [item for item in records if item["path"] == str(path)]
                self.assertEqual(match["sources"], ["runtime", "process"])
                self.assertTrue(match["running"])
                self.assertIsNone(match["responsive"])
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    def test_kernel_survives_launcher_exit_and_is_discovered_from_custom_path(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "custom-connection.json"
            command = [sys.executable, "-m", "jupyter_kernel_client.cli", "kernel", "start",
                       "--python", sys.executable, "--cwd", root, "-f", str(path), "--json"]
            environment = dict(os.environ, JPY_PARENT_PID="999999999")
            result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            record = json.loads(result.stdout)
            process = psutil.Process(record["pid"])
            try:
                self.assertTrue(process.is_running())
                if os.name != "nt":
                    self.assertEqual(os.getsid(process.pid), process.pid)
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                response = eval_expression(str(path), "6 * 7", timeout=10)
                self.assertTrue(response.ok)
                self.assertEqual(response.result_python, 42)
                with patch.object(kernels, "jupyter_runtime_dir", return_value=str(Path(root) / "empty")):
                    records = kernels.discover_kernels(limit=0)
                match, = [item for item in records if item["path"] == str(path)]
                self.assertTrue(match["running"])
                self.assertIsNone(match["responsive"])
                self.assertEqual(match["sources"], ["process"])
                self.assertEqual(match["processes"][0]["pid"], record["pid"])
                self.assertNotIn("key", record)
                self.assertNotIn("key", match)
            finally:
                # This PID is captured from this test's own startup response.
                process.terminate()
                try:
                    process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


class StopTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.path = Path(self.root.name) / "kernel.json"
        self.path.write_text("{}")

    def test_unknown_process_reports_only_acknowledgement_and_uses_only_control(self):
        client = unittest.mock.Mock()
        client.shutdown.return_value = "request-id"
        client.get_control_msg.side_effect = [
            dict(msg_type="shutdown_reply", parent_header={"msg_id": "other-id"}),
            dict(msg_type="shutdown_reply", parent_header={"msg_id": "request-id"}),
        ]
        with patch.object(kernels, "_kernel_processes", return_value=[]), \
                patch.object(kernels, "BlockingKernelClient", return_value=client):
            result = kernels.stop_kernel(str(self.path))
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "shutdown_acknowledged")
        self.assertIsNone(result["stopped"])
        self.assertIsNone(result["pid"])
        client.start_channels.assert_called_once_with(
            shell=False, iopub=False, stdin=False, hb=False, control=True,
        )
        client.shutdown.assert_called_once_with(restart=False)
        client.stop_channels.assert_called_once()
        self.assertTrue(self.path.exists())

    def test_timeout_does_not_signal_or_delete_files(self):
        process = unittest.mock.Mock(pid=123)
        process.create_time.return_value = 1
        process.is_running.return_value = True
        process.status.return_value = psutil.STATUS_SLEEPING
        client = unittest.mock.Mock()
        client.get_control_msg.side_effect = Empty
        match = dict(pid=123, created=1, path=str(self.path))
        with patch.object(kernels, "_kernel_processes", return_value=[match]), \
                patch.object(kernels.psutil, "Process", return_value=process), \
                patch.object(kernels, "BlockingKernelClient", return_value=client):
            result = kernels.stop_kernel(str(self.path), timeout=0.01)
        self.assertFalse(result["ok"])
        self.assertFalse(result["stopped"])
        self.assertTrue(result["timed_out"])
        process.terminate.assert_not_called()
        process.kill.assert_not_called()
        self.assertTrue(self.path.exists())
        client.stop_channels.assert_called_once()

    def test_ambiguous_target_is_rejected_before_connecting(self):
        matches = [dict(pid=pid, created=1, path=str(self.path)) for pid in (123, 456)]
        with patch.object(kernels, "_kernel_processes", return_value=matches), \
                patch.object(kernels, "BlockingKernelClient") as client:
            with self.assertRaisesRegex(KernelClientError, "Multiple kernel processes"):
                kernels.stop_kernel(str(self.path))
        client.assert_not_called()

    def test_reused_pid_is_rejected_before_connecting(self):
        process = unittest.mock.Mock()
        process.create_time.return_value = 2
        match = dict(pid=123, created=1, path=str(self.path))
        with patch.object(kernels, "_kernel_processes", return_value=[match]), \
                patch.object(kernels.psutil, "Process", return_value=process), \
                patch.object(kernels, "BlockingKernelClient") as client:
            with self.assertRaisesRegex(KernelClientError, "process changed"):
                kernels.stop_kernel(str(self.path))
        client.assert_not_called()

    def test_channels_are_closed_on_receive_failure(self):
        client = unittest.mock.Mock()
        client.get_control_msg.side_effect = RuntimeError("receive failed")
        with patch.object(kernels, "_kernel_processes", return_value=[]), \
                patch.object(kernels, "BlockingKernelClient", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "receive failed"):
                kernels.stop_kernel(str(self.path))
        client.stop_channels.assert_called_once()

    def test_cli_requires_explicit_target_even_with_environment_default(self):
        with patch.dict(os.environ, {"JK_CONNECTION_FILE": str(self.path)}), \
                contextlib.redirect_stderr(io.StringIO()), \
                patch("jupyter_kernel_client.cli.stop_kernel") as stop:
            with self.assertRaises(SystemExit) as error:
                main(["kernel", "stop", "--json"])
        self.assertEqual(error.exception.code, 2)
        stop.assert_not_called()

    def test_cli_timeout_exit_code(self):
        result = dict(status="timeout", ok=False)
        with patch("jupyter_kernel_client.cli.stop_kernel", return_value=result) as stop, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(["kernel", "stop", "-f", str(self.path), "--json"])
        self.assertEqual(code, 124)
        self.assertEqual(json.loads(output.getvalue()), result)
        stop.assert_called_once_with(str(self.path), timeout=10.0)

    def test_invalid_timeout_and_missing_file(self):
        for value in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                kernels.stop_kernel(str(self.path), timeout=value)
        with self.assertRaisesRegex(KernelClientError, "does not exist"):
            kernels.stop_kernel(str(self.path.parent / "missing.json"))


if __name__ == "__main__":
    unittest.main()
