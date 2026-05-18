"""Multi-DB Alembic dispatcher.

Usage:
    python -m scripts.alembic_wrapper app upgrade head
    python -m scripts.alembic_wrapper brain upgrade head
    python -m scripts.alembic_wrapper app revision --autogenerate -m "add field"

Sets ALEMBIC_DB={app|brain} so app/migrations/env.py picks the right Base.metadata
and database URL.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "app" / "migrations"


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("app", "brain"):
        print("Usage: python -m scripts.alembic_wrapper {app|brain} <alembic args>", file=sys.stderr)
        return 2

    target = sys.argv[1]
    alembic_args = sys.argv[2:]

    env = os.environ.copy()
    env["ALEMBIC_DB"] = target

    versions_dir = MIGRATIONS_DIR / f"versions_{target}"
    versions_dir.mkdir(parents=True, exist_ok=True)

    ini_path = REPO_ROOT / ("alembic.ini" if target == "app" else f"alembic-{target}.ini")
    cmd = ["alembic", "-c", str(ini_path), *alembic_args]
    result = subprocess.run(cmd, env=env, cwd=REPO_ROOT)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
