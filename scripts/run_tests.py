"""Helper to run pytest with environment variables loaded."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

base_dir = Path(__file__).resolve().parent.parent
env_file = base_dir / "api" / ".env"
load_dotenv(env_file)

pipecat_src = str(base_dir / "pipecat" / "src")
if pipecat_src not in sys.path:
    sys.path.insert(0, pipecat_src)
if str(base_dir) not in sys.path:
    sys.path.insert(0, str(base_dir))

import pytest

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        args = ["api/tests/services/auth/test_rbac.py", "api/tests/services/pipeline/"]
    sys.exit(pytest.main(args))
