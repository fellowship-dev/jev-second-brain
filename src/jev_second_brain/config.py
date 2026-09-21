"""Project state lives outside the source vault."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectConfig:
    vault: Path
    state_dir: Path
    db_path: Path
    allow_private_provider: bool = False


def default_state_dir(vault: Path) -> Path:
    resolved = vault.expanduser().resolve()
    base = Path(
        os.environ.get("XDG_STATE_HOME")
        or os.environ.get("LOCALAPPDATA")
        or Path.home() / ".local" / "state"
    )
    identifier = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
    return base / "jev-second-brain" / identifier


def load_config(state_dir: Path) -> ProjectConfig:
    state = state_dir.expanduser().resolve()
    if os.name == "posix" and state.stat().st_mode & 0o077:
        raise ValueError("State directory permissions must exclude group and other users")
    data = json.loads((state / "config.json").read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise ValueError("Unsupported project configuration schema")
    vault = Path(data["vault"]).resolve()
    return ProjectConfig(
        vault=vault,
        state_dir=state,
        db_path=state / "index.sqlite",
        allow_private_provider=bool(data.get("allow_private_provider", False)),
    )


def init_project(vault: Path, *, state_dir: Path | None = None) -> ProjectConfig:
    source = vault.expanduser().resolve(strict=True)
    if not source.is_dir():
        raise ValueError(f"Vault is not a directory: {source}")
    state = (state_dir or default_state_dir(source)).expanduser().resolve()
    if state == source or source in state.parents:
        raise ValueError("State directory must be outside the source vault")
    config_path = state / "config.json"
    if config_path.exists():
        if os.name == "posix":
            state.chmod(0o700)
        existing = load_config(state)
        if existing.vault != source:
            raise ValueError(f"State directory already belongs to {existing.vault}")
        return existing
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        state.chmod(0o700)
    payload = {"schema": 1, "vault": str(source), "allow_private_provider": False}
    try:
        with config_path.open("x", encoding="utf-8") as output:
            json.dump(payload, output, indent=2)
            output.write("\n")
    except FileExistsError:
        existing = load_config(state)
        if existing.vault != source:
            raise ValueError(f"State directory already belongs to {existing.vault}")
        return existing
    if os.name == "posix":
        config_path.chmod(0o600)
    return load_config(state)
