import os
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(REPO_DIR))

from conftest import TEST_DATABASE_URL, reset_database  # noqa: E402


if __name__ == "__main__":
    env = os.environ.copy()
    env["DATABASE_URL"] = TEST_DATABASE_URL
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"alembic upgrade failed:\n{result.stdout}{result.stderr}")
    reset_database()
