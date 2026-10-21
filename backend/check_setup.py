"""Validate the local Python environment and required project configuration."""

from __future__ import annotations

import os
import sys
from importlib.util import find_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_PACKAGES = (
    "bs4",
    "fastapi",
    "google.genai",
    "pydantic_settings",
    "requests",
    "supabase",
    "uvicorn",
)


def read_local_env() -> dict[str, str]:
    """Read simple KEY=VALUE entries from .env without requiring dependencies."""
    env_path = ROOT / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def package_is_installed(package: str) -> bool:
    """Check an import name, including nested names, without raising on missing parents."""
    try:
        return find_spec(package) is not None
    except ModuleNotFoundError:
        return False


def main() -> int:
    """Print setup diagnostics and return a process exit code."""
    errors: list[str] = []

    print(f"Python: OK ({sys.version.split()[0]})")

    missing_packages = [package for package in REQUIRED_PACKAGES if not package_is_installed(package)]
    if missing_packages:
        errors.append(f"Missing packages: {', '.join(missing_packages)}. Install with pip install -e \".[dev]\".")
    else:
        print("Dependencies: OK")

    if not (ROOT / ".env").exists():
        print(
            "Environment file: .env not found; create it in the project root and set "
            "GEMINI_API_KEY, SUPABASE_URL, SUPABASE_KEY, and SOURCE_URL."
        )

    local_env = read_local_env()
    missing_settings = [
        name
        for name in ("GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY", "SOURCE_URL")
        if not os.environ.get(name) and not local_env.get(name)
    ]
    if missing_settings:
        print(f"Configuration: pending values for {', '.join(missing_settings)}")
    else:
        print("Configuration: required values are set")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Setup check passed. Fill in the listed configuration values before using external services.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
