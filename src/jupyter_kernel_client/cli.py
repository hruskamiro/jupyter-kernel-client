from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable, List, Optional

from .client import (
    InterruptResponse,
    KernelClientError,
    KernelResponse,
    execute,
    eval_expression,
    get_variable,
    interrupt_kernel,
)
from .skill import SkillInstallError, codex_skill_path, install_codex_skill
from .kernels import discover_kernels, start_kernel, stop_kernel


def _default_connection_file() -> Optional[str]:
    return os.environ.get("JK_CONNECTION_FILE") or os.environ.get("JUPYTER_CONNECTION_FILE")


def _read_code(args: argparse.Namespace) -> str:
    sources = [bool(args.code), bool(args.file), bool(args.stdin)]
    if sum(sources) != 1:
        raise KernelClientError("Provide exactly one code source: argument, --file, or --stdin.")
    if args.stdin:
        return sys.stdin.read()
    if args.file:
        return Path(args.file).expanduser().read_text()
    return args.code


def _print_human(response: KernelResponse) -> int:
    if response.stdout:
        sys.stdout.write(response.stdout)
    if response.stderr:
        sys.stderr.write(response.stderr)

    if response.status == "timeout":
        sys.stderr.write(f"Timed out after {response.elapsed_seconds:.2f}s. Kernel execution may still be running.\n")
        return 124

    if response.status == "error":
        if response.traceback:
            sys.stderr.write("\n".join(response.traceback) + "\n")
        elif response.ename or response.evalue:
            sys.stderr.write(f"{response.ename}: {response.evalue}\n")
        return 1

    if response.result_text is not None:
        sys.stdout.write(f"{response.result_text}\n")
    return 0


def _emit_response(response: KernelResponse, *, json_output: bool) -> int:
    if json_output:
        print(json.dumps(response.to_dict(), ensure_ascii=True))
        if response.status == "timeout":
            return 124
        return 0 if response.ok else 1
    return _print_human(response)


def _emit_interrupt_response(response: InterruptResponse, *, json_output: bool) -> int:
    if json_output:
        print(json.dumps(response.to_dict(), ensure_ascii=True))
    elif response.status == "sent":
        print(f"Sent interrupt request: {response.msg_id}")
    elif response.ok:
        print(f"Interrupted kernel: {response.msg_id}")
    elif response.status == "timeout":
        print(f"Timed out waiting for interrupt reply after {response.elapsed_seconds:.2f}s.", file=sys.stderr)
    elif response.error:
        print(f"Interrupt failed: {response.error}", file=sys.stderr)
    else:
        print(f"Interrupt failed with status: {response.status}", file=sys.stderr)

    if response.status == "timeout":
        return 124
    return 0 if response.ok else 1


def _resolve_connection_file(args: argparse.Namespace) -> str:
    connection_file = args.connection_file or _default_connection_file()
    if connection_file:
        return str(Path(connection_file).expanduser())
    raise KernelClientError(
        "No connection file provided. Use --connection-file, JK_CONNECTION_FILE, "
        "JUPYTER_CONNECTION_FILE, or run `jk kernels` to list candidates."
    )


def _add_common_options(parser: argparse.ArgumentParser, *, timeout_help: str = "Seconds to wait for execution completion.") -> None:
    parser.add_argument(
        "--connection-file",
        "-f",
        help="Path to a Jupyter kernel connection JSON file. Defaults to JK_CONNECTION_FILE or JUPYTER_CONNECTION_FILE.",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help=timeout_help)
    parser.add_argument("--json", action="store_true", help="Emit stable structured JSON output.")


def _vars_code(*, include_private: bool, repr_length: int) -> str:
    private_check = "True" if include_private else "not name.startswith('_')"
    return f"""
[
    {{
        "name": name,
        "type": type(value).__module__ + "." + type(value).__qualname__,
        "repr": repr(value)[:{repr_length}],
    }}
    for name, value in sorted(globals().items())
    if {private_check}
    and name not in {{"In", "Out", "exit", "quit", "get_ipython"}}
]
""".strip()


def _run_demo(connection_file: str, *, timeout: float, json_output: bool) -> int:
    snippets = [
        ("stdout_and_result", "print('hello from jk')\n21 * 2"),
        ("state_write", "jk_demo_value = {'ready': True, 'items': [1, 2, 3]}\njk_demo_value"),
        ("state_read", "jk_demo_value"),
        ("rich_output", "from IPython.display import display, HTML\ndisplay(HTML('<b>jk html output</b>'))\n'ok'"),
    ]

    results = []
    exit_code = 0
    for name, code in snippets:
        response = execute(connection_file, code, timeout=timeout)
        results.append({"name": name, "response": response.to_dict()})
        if not response.ok and exit_code == 0:
            exit_code = 124 if response.status == "timeout" else 1

    if json_output:
        print(json.dumps({"status": "ok" if exit_code == 0 else "error", "ok": exit_code == 0, "checks": results}, ensure_ascii=True))
        return exit_code

    for result in results:
        response = result["response"]
        status = "ok" if response["ok"] else response["status"]
        print(f"{result['name']}: {status}")
        if response["stdout"]:
            print(response["stdout"], end="")
        if response["result_text"] is not None:
            print(response["result_text"])
        if response["outputs"]:
            print(f"outputs: {len(response['outputs'])}")
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jk", description="Start, discover, and work with Jupyter kernels.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    exec_parser = subparsers.add_parser("exec", help="Execute code.")
    _add_common_options(exec_parser)
    exec_parser.add_argument("code", nargs="?", help="Code to execute.")
    exec_parser.add_argument("--file", "-i", help="Read code from a file.")
    exec_parser.add_argument("--stdin", action="store_true", help="Read code from standard input.")
    exec_parser.add_argument("--silent", action="store_true", help="Execute silently.")
    exec_parser.add_argument("--no-history", action="store_true", help="Do not store execution in kernel history.")

    eval_parser = subparsers.add_parser("eval", help="Evaluate a Python expression.")
    _add_common_options(eval_parser)
    eval_parser.add_argument("expression", help="Python expression to evaluate.")

    get_parser = subparsers.add_parser("get", help="Get a variable by name.")
    _add_common_options(get_parser)
    get_parser.add_argument("name", help="Variable name to fetch from the kernel.")

    vars_parser = subparsers.add_parser("vars", help="Inspect user-visible variables in the kernel namespace.")
    _add_common_options(vars_parser)
    vars_parser.add_argument("--include-private", action="store_true", help="Include names beginning with underscore.")
    vars_parser.add_argument("--repr-length", type=int, default=160, help="Maximum repr length per variable.")

    demo_parser = subparsers.add_parser("demo", help="Run a short capability demo against a kernel.")
    _add_common_options(demo_parser)

    interrupt_parser = subparsers.add_parser("interrupt", help="Send KeyboardInterrupt to a running kernel.")
    _add_common_options(interrupt_parser, timeout_help="Seconds to wait for an interrupt reply.")
    interrupt_parser.add_argument("--no-wait", action="store_true", help="Do not wait for an interrupt reply.")

    kernel_parser = subparsers.add_parser("kernel", help="Explicit kernel lifecycle operations.")
    kernel_commands = kernel_parser.add_subparsers(dest="kernel_command", required=True)
    start_parser = kernel_commands.add_parser("start", help="Start a detached Python kernel and wait for readiness.")
    start_parser.add_argument("--python", help="Python executable containing ipykernel (default: jk's Python).")
    start_parser.add_argument("--connection-file", "-f", help="New connection path (default: unique runtime-directory file).")
    start_parser.add_argument("--cwd", help="Kernel working directory (default: current directory).")
    start_parser.add_argument("--log", help="New log path (default: connection path with .log suffix).")
    start_parser.add_argument("--timeout", type=float, default=30.0, help="Startup readiness timeout in seconds.")
    start_parser.add_argument("--json", action="store_true", help="Emit JSON with PID, connection path and log path.")
    stop_parser = kernel_commands.add_parser("stop", help="Request graceful shutdown; never force-kill.")
    stop_parser.add_argument("--connection-file", "-f", required=True, help="Explicit connection file of the kernel to stop.")
    stop_parser.add_argument("--timeout", type=float, default=10.0, help="Seconds to wait for shutdown confirmation.")
    stop_parser.add_argument("--json", action="store_true", help="Emit shutdown acknowledgement and process-exit status.")

    kernels_parser = subparsers.add_parser("kernels", help="Discover current-user local kernels from runtime files and processes.")
    kernels_parser.add_argument("--json", action="store_true", help="Emit JSON.")
    kernels_parser.add_argument("--limit", type=int, default=20, help="Maximum records to list, live processes first. Use 0 for no limit.")
    kernels_parser.add_argument("--probe", action="store_true", help="Connect to each listed file and report whether it responds.")
    kernels_parser.add_argument("--timeout", type=float, default=1.0, help="Seconds to wait per probed kernel.")

    skill_parser = subparsers.add_parser("skill", help="Manage the bundled Codex skill.")
    skill_subparsers = skill_parser.add_subparsers(dest="skill_command", required=True)

    skill_install_parser = skill_subparsers.add_parser(
        "install",
        help="Install the jk skill for the current Codex user.",
    )
    skill_install_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing jk skill when its contents differ.",
    )
    skill_install_parser.add_argument(
        "--dest",
        help="Install to this exact skill directory instead of the user Codex directory.",
    )

    skill_path_parser = skill_subparsers.add_parser(
        "path",
        help="Print the user-level installation path for the jk skill.",
    )
    skill_path_parser.add_argument(
        "--dest",
        help="Print this explicit skill directory instead of the user Codex directory.",
    )

    return parser


def _normalize_argv(argv: Optional[Iterable[str]]) -> Optional[List[str]]:
    if argv is None:
        values = sys.argv[1:]
    else:
        values = list(argv)

    commands = {"exec", "eval", "get", "vars", "demo", "interrupt", "kernels", "kernel", "skill"}
    command_positions = [index for index, value in enumerate(values) if value in commands]
    if not command_positions:
        return values if argv is not None else None

    command_index = command_positions[0]
    if command_index == 0:
        return values if argv is not None else None

    normalized = [values[command_index], *values[:command_index], *values[command_index + 1 :]]
    return normalized


def _list_kernels(*, json_output: bool, limit: int, probe: bool, timeout: float) -> int:
    records = discover_kernels(limit=limit, probe=probe, timeout=timeout)
    if json_output:
        print(json.dumps(records, ensure_ascii=True))
        return 0
    if not records:
        print("No kernel candidates found.")
        return 1
    for record in records:
        status = "running" if record["running"] else "file-only"
        if probe and record["responsive"] is not None:
            status += "/responsive" if record["responsive"] else "/unresponsive"
        pids = ",".join(str(process["pid"]) for process in record["processes"]) or "-"
        print(f"{status:24} pid={pids:10} {record['path'] or '(connection path unknown)'}")
    return 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(_normalize_argv(argv))

    try:
        if args.command == "kernels":
            return _list_kernels(json_output=args.json, limit=args.limit, probe=args.probe, timeout=args.timeout)
        if args.command == "kernel" and args.kernel_command == "start":
            record = start_kernel(python=args.python, connection_file=args.connection_file,
                                  cwd=args.cwd, log=args.log, timeout=args.timeout)
            if args.json:
                print(json.dumps(record, ensure_ascii=True))
            else:
                print(f"Started kernel PID {record['pid']}\nConnection: {record['path']}\nLog: {record['log']}")
            return 0
        if args.command == "kernel" and args.kernel_command == "stop":
            record = stop_kernel(args.connection_file, timeout=args.timeout)
            if args.json:
                print(json.dumps(record, ensure_ascii=True))
            elif record["status"] == "stopped":
                print(f"Stopped kernel PID {record['pid']}: {record['path']}")
            elif record["ok"]:
                print(f"Shutdown acknowledged; process exit not verified: {record['path']}")
            else:
                print(f"Shutdown not confirmed within {args.timeout:g}s; the request may still complete: {record['path']}",
                      file=sys.stderr)
            return 0 if record["ok"] else 124
        if args.command == "skill":
            if args.skill_command == "path":
                print(codex_skill_path(destination=args.dest))
                return 0
            if args.skill_command == "install":
                path, changed = install_codex_skill(destination=args.dest, force=args.force)
                if changed:
                    print(f"Installed jk Codex skill at {path}")
                    print("The skill will be available in a new Codex turn or session.")
                else:
                    print(f"jk Codex skill is already up to date at {path}")
                return 0

        connection_file = _resolve_connection_file(args)
        if args.command == "exec":
            code = _read_code(args)
            response = execute(
                connection_file,
                code,
                timeout=args.timeout,
                silent=args.silent,
                store_history=not args.no_history,
            )
        elif args.command == "eval":
            response = eval_expression(connection_file, args.expression, timeout=args.timeout)
        elif args.command == "get":
            response = get_variable(connection_file, args.name, timeout=args.timeout)
        elif args.command == "vars":
            response = execute(
                connection_file,
                _vars_code(include_private=args.include_private, repr_length=args.repr_length),
                timeout=args.timeout,
            )
        elif args.command == "demo":
            return _run_demo(connection_file, timeout=args.timeout, json_output=args.json)
        elif args.command == "interrupt":
            response = interrupt_kernel(connection_file, timeout=args.timeout, wait=not args.no_wait)
            return _emit_interrupt_response(response, json_output=args.json)
        else:
            parser.error(f"Unknown command: {args.command}")
    except SkillInstallError as exc:
        print(f"Skill install error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if getattr(args, "json", False):
            print(json.dumps({"status": "client_error", "ok": False, "error": str(exc)}, ensure_ascii=True))
        else:
            print(f"Client error: {exc}", file=sys.stderr)
        return 2

    return _emit_response(response, json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
