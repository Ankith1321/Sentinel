import os
import tempfile
from pathlib import Path

TEST_DB_DIR = tempfile.mkdtemp(prefix="sentinel-test-")

os.environ["SENTINEL_DB_PATH"] = str(Path(TEST_DB_DIR) / "sentinel-test.db")
os.environ["SENTINEL_WARMUP"] = "off"
os.environ["SENTINEL_API_KEY"] = "test-admin-key"
os.environ["SENTINEL_AUTH"] = "on"
os.environ["SENTINEL_VERIFIED_SNAPSHOT"] = str(Path(TEST_DB_DIR) / "verified_answers.json")
