from __future__ import annotations

import os
from pathlib import Path


def load_env(env_path: Path | str | None = None) -> bool:
    """Load environment variables from a .env file into os.environ.

    Attempts to use python-dotenv if available, and falls back to a built-in
    parser if not. Does not overwrite already-set environment variables.
    """
    if env_path is None:
        # Search starting from current directory up to git/project root
        candidate = Path.cwd() / ".env"
        if not candidate.is_file():
            # Check repository root relative to this module
            repo_candidate = Path(__file__).resolve().parent.parent.parent / ".env"
            if repo_candidate.is_file():
                candidate = repo_candidate
        target = candidate
    else:
        target = Path(env_path)

    if not target.is_file():
        return False

    try:
        from dotenv import load_dotenv
        return load_dotenv(target, override=False)
    except ImportError:
        # Minimal fallback parser
        try:
            with open(target, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip()
                        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                            v = v[1:-1]
                        if k and k not in os.environ:
                            os.environ[k] = v
            return True
        except Exception:
            return False


# Automatically load on import
load_env()
