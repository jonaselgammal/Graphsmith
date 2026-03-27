"""First-class environment ops for filesystem and process execution."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from graphsmith.exceptions import OpError


def fs_read_text(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Read a UTF-8 text file from an allowed root."""
    raw_path = inputs.get("path", config.get("path"))
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise OpError("fs.read_text requires input 'path'")
    path = _resolve_allowed_path(raw_path, config=config)
    encoding = config.get("encoding", "utf-8")
    if not isinstance(encoding, str) or not encoding:
        raise OpError("fs.read_text config.encoding must be a non-empty string")
    return {"text": path.read_text(encoding=encoding)}


def fs_write_text(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Write a UTF-8 text file under an allowed root."""
    raw_path = inputs.get("path", config.get("path"))
    text = inputs.get("text", config.get("text"))
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise OpError("fs.write_text requires input 'path'")
    if not isinstance(text, str):
        raise OpError("fs.write_text requires input 'text'")
    path = _resolve_allowed_path(raw_path, config=config)
    encoding = config.get("encoding", "utf-8")
    if not isinstance(encoding, str) or not encoding:
        raise OpError("fs.write_text config.encoding must be a non-empty string")
    mkdirs = config.get("mkdirs", True)
    if mkdirs:
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)
    return {"path": str(path), "written": len(text)}


def shell_exec(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Run a bounded subprocess without invoking a shell parser."""
    argv = inputs.get("argv", config.get("argv"))
    if isinstance(argv, str):
        argv = [argv]
    if not isinstance(argv, list) or not argv or not all(isinstance(v, str) and v for v in argv):
        raise OpError("shell.exec requires input/config 'argv' as a non-empty list of strings")

    cwd_value = inputs.get("cwd", config.get("cwd"))
    cwd = None
    if cwd_value is not None:
        if not isinstance(cwd_value, str) or not cwd_value.strip():
            raise OpError("shell.exec cwd must be a non-empty string")
        cwd = str(_resolve_allowed_path(cwd_value, config=config, require_existing_dir=True))

    stdin = inputs.get("stdin", config.get("stdin"))
    if stdin is not None and not isinstance(stdin, str):
        raise OpError("shell.exec stdin must be a string if provided")

    timeout_ms = config.get("timeout_ms", 5000)
    if not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise OpError("shell.exec config.timeout_ms must be a positive integer")
    check = bool(config.get("check", False))

    env = os.environ.copy()
    env_allow = config.get("env_allow", [])
    if env_allow:
        if not isinstance(env_allow, list) or not all(isinstance(v, str) for v in env_allow):
            raise OpError("shell.exec config.env_allow must be a list of strings")
        env = {key: value for key, value in env.items() if key in set(env_allow)}

    try:
        proc = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
            timeout=timeout_ms / 1000,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OpError(f"shell.exec timed out after {timeout_ms}ms") from exc
    except OSError as exc:
        raise OpError(f"shell.exec failed: {exc}") from exc

    if check and proc.returncode != 0:
        raise OpError(
            f"shell.exec returned non-zero exit code {proc.returncode}: "
            f"{(proc.stderr or proc.stdout).strip()}"
        )

    return {
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "exit_code": proc.returncode,
    }


def _resolve_allowed_path(
    raw_path: str,
    *,
    config: dict[str, Any],
    require_existing_dir: bool = False,
) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    resolved = path.resolve(strict=False)

    allow_roots = config.get("allow_roots")
    if allow_roots is None:
        roots = [Path.cwd()]
    else:
        if not isinstance(allow_roots, list) or not all(isinstance(v, str) and v for v in allow_roots):
            raise OpError("environment op config.allow_roots must be a list of non-empty strings")
        roots = [Path(root).expanduser().resolve(strict=False) for root in allow_roots]

    if not any(_is_relative_to(resolved, root) for root in roots):
        allowed = ", ".join(str(root) for root in roots)
        raise OpError(f"Path '{resolved}' is outside allowed roots: {allowed}")

    if require_existing_dir and not resolved.is_dir():
        raise OpError(f"Working directory '{resolved}' does not exist or is not a directory")

    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
