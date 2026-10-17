import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(REPO_DIR))

from conftest import reset_database  # noqa: E402


if __name__ == "__main__":
    reset_database()
