#!/usr/bin/env python3
"""
Central development workflow runner for the Blind Debate Adjudicator.

This script keeps the local development loop in one place:
- bootstrap dependencies into the project's venv
- run the existing test scripts
- start the preferred server version
- run a smoke test against a temporary local server
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = REPO_ROOT / "venv"
DOTENV_PATH = REPO_ROOT / ".env"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
DEFAULT_SMOKE_PORT = 5055
DEFAULT_ACCEPTANCE_PORT = 5080
DEFAULT_SERVER_VERSION = "v3"
MANUAL_COMMANDS = (
    "server-check",
    "scenario-ai",
    "scenario-energy",
    "modulation",
)


def parse_env_line(raw_line: str) -> tuple[str, str] | None:
    """Parse a simple KEY=VALUE dotenv line."""
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None

    if line.startswith("export "):
        line = line[len("export ") :].strip()

    key, separator, value = line.partition("=")
    if not separator:
        return None

    key = key.strip()
    value = value.strip()

    if value and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]

    return key, value


def project_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Build the subprocess environment, including .env when present."""
    env = os.environ.copy()

    if DOTENV_PATH.exists():
        for raw_line in DOTENV_PATH.read_text(encoding="utf-8").splitlines():
            parsed = parse_env_line(raw_line)
            if not parsed:
                continue
            key, value = parsed
            env.setdefault(key, value)

    if overrides:
        env.update({key: str(value) for key, value in overrides.items() if value is not None})

    return env


def venv_executable(name: str) -> Path:
    """Return the expected path to an executable inside venv."""
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return VENV_DIR / scripts_dir / f"{name}{suffix}"


def active_python() -> str:
    """Use the project virtualenv when available, otherwise the current Python."""
    candidate = venv_executable("python")
    return str(candidate if candidate.exists() else Path(sys.executable))


def run_command(
    command: Iterable[str],
    env: dict[str, str] | None = None,
    check: bool = True,
) -> int:
    """Run a command from the repo root with a visible shell-style echo."""
    command_list = [str(part) for part in command]
    print(f"$ {' '.join(command_list)}")
    result = subprocess.run(command_list, cwd=REPO_ROOT, env=env, check=False)

    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, command_list)

    return result.returncode


def ensure_venv() -> None:
    """Create the local virtual environment if missing."""
    if VENV_DIR.exists():
        return

    print(f"Creating virtual environment at {VENV_DIR}")
    subprocess.run(
        [sys.executable, "-m", "venv", str(VENV_DIR)],
        cwd=REPO_ROOT,
        check=True,
    )


def wait_for_health(base_url: str, timeout_seconds: int, process: subprocess.Popen) -> None:
    """Wait until the Flask health endpoint returns 200."""
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    health_url = f"{base_url}/api/health"

    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server exited early with code {process.returncode}")

        try:
            with urlopen(health_url, timeout=2) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError, OSError) as exc:
            last_error = exc

        time.sleep(1)

    raise RuntimeError(f"Timed out waiting for {health_url}: {last_error}")


def assert_port_available(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as exc:
            raise RuntimeError(
                f"Port {port} is already in use on {host}. Stop the existing "
                "server or choose a different port with --port. If a previous "
                "run just exited, wait a moment for the OS to release the port."
            ) from exc


def stop_process(process: subprocess.Popen) -> None:
    """Terminate a background process cleanly."""
    if process.poll() is not None:
        return

    try:
        if os.name == "nt":
            process.terminate()
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def bootstrap(_: argparse.Namespace) -> None:
    """Create venv and install project requirements."""
    ensure_venv()
    python = active_python()
    env = project_env()
    run_command([python, "-m", "pip", "install", "--upgrade", "pip"], env=env)
    run_command([python, "-m", "pip", "install", "-r", "requirements.txt"], env=env)


def run_unit_tests(_: argparse.Namespace) -> None:
    """Run the main unit and integration script."""
    run_command(
        [active_python(), "-m", "pytest", "tests/integration/test_debate_system.py"],
        env=project_env(),
    )


def run_fact_tests(_: argparse.Namespace) -> None:
    """Run the fact-checking focused test script."""
    run_command(
        [active_python(), "-m", "pytest", "tests/unit/test_fact_check_skill.py"], env=project_env()
    )


def run_check(_: argparse.Namespace) -> None:
    """Run the default pre-commit style checks for the repo."""
    env = project_env()
    failures = []

    unit_code = run_command(
        [active_python(), "-m", "pytest", "tests/integration/test_debate_system.py"],
        env=env,
        check=False,
    )
    if unit_code != 0:
        failures.append(("unit", unit_code))

    fact_code = run_command(
        [active_python(), "-m", "pytest", "tests/unit/test_fact_check_skill.py"],
        env=env,
        check=False,
    )
    if fact_code != 0:
        failures.append(("fact", fact_code))

    if failures:
        summary = ", ".join(f"{name} (exit {code})" for name, code in failures)
        raise RuntimeError(f"One or more suites failed: {summary}")


def run_manual(args: argparse.Namespace) -> None:
    """Run one of the manual API scenarios against an existing server."""
    env = project_env({"DEBATE_BASE_URL": args.base_url})
    run_command(
        [
            active_python(),
            "tests/manual/manual_scenarios.py",
            args.command,
            "--base-url",
            args.base_url,
        ],
        env=env,
    )


def build_server_command(args: argparse.Namespace) -> list[str]:
    """Translate CLI flags into the existing startup scripts."""
    python = active_python()

    if args.version == "v1":
        command = [python, "start_server.py", "--host", args.host, "--port", str(args.port)]
        if args.fact_mode:
            command.extend(["--fact-mode", args.fact_mode])
    elif args.version == "fast":
        command = [python, "start_server_fast.py", "--host", args.host, "--port", str(args.port)]
    elif args.version == "v2":
        command = [python, "start_server_v2.py", "--host", args.host, "--port", str(args.port)]
        if args.fact_mode:
            command.extend(["--fact-mode", args.fact_mode])
        if args.llm_provider:
            command.extend(["--llm-provider", args.llm_provider])
        if args.num_judges:
            command.extend(["--num-judges", str(args.num_judges)])
        if args.db_path:
            command.extend(["--db-path", args.db_path])
        if args.debug:
            command.append("--debug")
    else:
        command = [python, "start_server_v3.py", "--host", args.host, "--port", str(args.port)]
        if args.fact_mode:
            command.extend(["--fact-mode", args.fact_mode])
        if args.llm_provider:
            command.extend(["--llm-provider", args.llm_provider])
        if args.num_judges:
            command.extend(["--num-judges", str(args.num_judges)])
        if args.db_path:
            command.extend(["--db-path", args.db_path])
        if args.debug:
            command.append("--debug")

    if args.server_args:
        command.extend(args.server_args)

    return command


def run_server(args: argparse.Namespace) -> None:
    """Start one of the supported local server modes."""
    run_command(build_server_command(args), env=project_env())


def run_smoke(args: argparse.Namespace) -> None:
    """Start a temporary v3 server and run a lightweight API scenario."""
    base_url = f"http://{DEFAULT_HOST}:{args.port}"
    assert_port_available(DEFAULT_HOST, args.port)
    env = project_env({"PYTHONUNBUFFERED": "1", "ENABLE_RATE_LIMITER": "false"})
    temp_db_path = Path(tempfile.gettempdir()) / f"debate_system_smoke_{args.port}.db"

    if temp_db_path.exists():
        temp_db_path.unlink()

    command = [
        active_python(),
        "start_server_v3.py",
        "--host",
        DEFAULT_HOST,
        "--port",
        str(args.port),
        "--db-path",
        str(temp_db_path),
        "--fact-mode",
        "OFFLINE",
        "--llm-provider",
        "mock",
        "--num-judges",
        "3",
    ]

    print(f"$ {' '.join(command)}")
    process = subprocess.Popen(command, cwd=REPO_ROOT, env=env)

    try:
        wait_for_health(base_url, args.timeout, process)
        run_command(
            [
                active_python(),
                "tests/manual/manual_scenarios.py",
                args.scenario,
                "--base-url",
                base_url,
            ],
            env=project_env({"DEBATE_BASE_URL": base_url}),
        )
    finally:
        stop_process(process)


def run_acceptance(args: argparse.Namespace) -> None:
    """Start a temporary v3 server and run the browser-driven acceptance suite."""
    base_url = f"http://{DEFAULT_HOST}:{args.port}"
    assert_port_available(DEFAULT_HOST, args.port)
    env = project_env(
        {
            "PYTHONUNBUFFERED": "1",
            "ENABLE_RATE_LIMITER": "false",
            "ENV": "development",
            "ALLOWED_ORIGINS": "",
            "ADMIN_ACCESS_MODE": "authenticated",
            "ADMIN_USER_EMAILS": "",
            "ADMIN_USER_IDS": "",
            "DISABLE_JOB_WORKER": "",
        }
    )
    temp_db_path = Path(tempfile.gettempdir()) / f"debate_system_acceptance_{args.port}.db"

    if temp_db_path.exists():
        temp_db_path.unlink()

    command = [
        active_python(),
        "start_server_v3.py",
        "--host",
        DEFAULT_HOST,
        "--port",
        str(args.port),
        "--fact-mode",
        "OFFLINE",
        "--llm-provider",
        "mock",
        "--num-judges",
        "3",
        "--db-path",
        str(temp_db_path),
    ]

    print(f"$ {' '.join(command)}")
    process = subprocess.Popen(command, cwd=REPO_ROOT, env=env)

    try:
        wait_for_health(base_url, args.timeout, process)
        acceptance_command = [
            active_python(),
            "acceptance/run_ui_acceptance.py",
            "--base-url",
            base_url,
        ]
        if args.headed:
            acceptance_command.append("--headed")

        run_command(acceptance_command, env=project_env())
    finally:
        stop_process(process)


def run_a11y(args: argparse.Namespace) -> None:
    """Start a temporary v3 server and run the accessibility scan."""
    base_url = f"http://{DEFAULT_HOST}:{args.port}"
    assert_port_available(DEFAULT_HOST, args.port)
    env = project_env({"PYTHONUNBUFFERED": "1", "ENABLE_RATE_LIMITER": "false"})
    temp_db_path = Path(tempfile.gettempdir()) / f"debate_system_a11y_{args.port}.db"

    if temp_db_path.exists():
        temp_db_path.unlink()

    command = [
        active_python(),
        "start_server_v3.py",
        "--host",
        DEFAULT_HOST,
        "--port",
        str(args.port),
        "--fact-mode",
        "OFFLINE",
        "--llm-provider",
        "mock",
        "--num-judges",
        "3",
        "--db-path",
        str(temp_db_path),
    ]

    print(f"$ {' '.join(command)}")
    process = subprocess.Popen(command, cwd=REPO_ROOT, env=env)

    try:
        wait_for_health(base_url, args.timeout, process)
        a11y_command = [
            active_python(),
            "acceptance/run_a11y_scan.py",
            "--base-url",
            base_url,
        ]
        if args.impact:
            a11y_command.extend(["--impact", args.impact])

        run_command(a11y_command, env=project_env())
    finally:
        stop_process(process)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        description="Automation helpers for the Blind Debate Adjudicator development loop.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Create venv and install requirements.",
    )
    bootstrap_parser.set_defaults(func=bootstrap)

    unit_parser = subparsers.add_parser(
        "unit",
        help="Run tests/integration/test_debate_system.py.",
    )
    unit_parser.set_defaults(func=run_unit_tests)

    fact_parser = subparsers.add_parser(
        "fact",
        help="Run tests/unit/test_fact_check_skill.py.",
    )
    fact_parser.set_defaults(func=run_fact_tests)

    check_parser = subparsers.add_parser(
        "check",
        help="Run the default local verification suite.",
    )
    check_parser.set_defaults(func=run_check)

    manual_parser = subparsers.add_parser(
        "manual",
        help="Run one of the manual API scenarios against an already running server.",
    )
    manual_parser.add_argument("command", choices=MANUAL_COMMANDS)
    manual_parser.add_argument(
        "--base-url", default=os.getenv("DEBATE_BASE_URL", f"http://{DEFAULT_HOST}:{DEFAULT_PORT}")
    )
    manual_parser.set_defaults(func=run_manual)

    server_parser = subparsers.add_parser(
        "server",
        help="Start one of the app server variants.",
    )
    server_parser.add_argument(
        "--version", choices=("v1", "v2", "v3", "fast"), default=DEFAULT_SERVER_VERSION
    )
    server_parser.add_argument("--host", default="0.0.0.0")
    server_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    server_parser.add_argument("--db-path")
    server_parser.add_argument("--fact-mode", choices=("OFFLINE", "ONLINE_ALLOWLIST"))
    server_parser.add_argument(
        "--llm-provider", choices=("mock", "openai", "openrouter", "openrouter-multi")
    )
    server_parser.add_argument("--num-judges", type=int)
    server_parser.add_argument("--debug", action="store_true")
    server_parser.add_argument("server_args", nargs=argparse.REMAINDER)
    server_parser.set_defaults(func=run_server)

    smoke_parser = subparsers.add_parser(
        "smoke",
        help="Start a temporary v3 server and run an automated API scenario.",
    )
    smoke_parser.add_argument("--scenario", choices=MANUAL_COMMANDS, default="server-check")
    smoke_parser.add_argument("--port", type=int, default=DEFAULT_SMOKE_PORT)
    smoke_parser.add_argument("--timeout", type=int, default=30)
    smoke_parser.set_defaults(func=run_smoke)

    acceptance_parser = subparsers.add_parser(
        "acceptance",
        help="Start a temporary v3 server and run browser-based acceptance checks.",
    )
    acceptance_parser.add_argument("--port", type=int, default=DEFAULT_ACCEPTANCE_PORT)
    acceptance_parser.add_argument("--timeout", type=int, default=45)
    acceptance_parser.add_argument("--headed", action="store_true")
    acceptance_parser.set_defaults(func=run_acceptance)

    a11y_parser = subparsers.add_parser(
        "a11y",
        help="Start a temporary v3 server and run an accessibility scan.",
    )
    a11y_parser.add_argument("--port", type=int, default=DEFAULT_ACCEPTANCE_PORT)
    a11y_parser.add_argument("--timeout", type=int, default=45)
    a11y_parser.add_argument(
        "--impact", default="critical", help="Impact threshold (default: critical)"
    )
    a11y_parser.set_defaults(func=run_a11y)

    return parser


def main() -> int:
    """Program entry point."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        args.func(args)
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # pragma: no cover - defensive CLI error handling
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
