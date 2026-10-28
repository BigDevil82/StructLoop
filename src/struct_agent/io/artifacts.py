"""Exclusive run directories and JSON artifacts; never overwrite existing runs."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from importlib.metadata import distributions
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_safe(value: Any) -> Any:
    """Nonfinite legacy values remain explicit missing values, never fake numbers."""
    import math
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(v) for v in value]
    return value


def write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(json_safe(value), stream, ensure_ascii=False, indent=2, allow_nan=False)


def create_run(path: Path, *, seed: int, inputs: dict[str, Path], config: dict[str, Any]) -> None:
    path.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[3]
    code_files = sorted((root / "src").rglob("*.py"))
    code_hash = hashlib.sha256("".join(f"{p.relative_to(root)}:{sha256(p)}\n" for p in code_files).encode()).hexdigest()
    # Fixed read-only version query, no caller-supplied command execution.
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    write_json(path / "manifest.json", {
        "seed": seed, "config": config, "python": platform.python_version(),
        "git_commit": git.stdout.strip() if git.returncode == 0 else None,
        "code_sha256": code_hash,
        "software": {d.metadata["Name"]: d.version for d in distributions()},
        "inputs": {k: {"path": str(v.resolve()), "sha256": sha256(v)} for k, v in inputs.items()},
    })
