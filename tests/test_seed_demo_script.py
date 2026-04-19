from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from app.storage import Storage


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "seed_demo.py"


def test_seed_demo_script_creates_demo_dataset(tmp_path):
    target_dir = tmp_path / "demo-data"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--data-dir",
            str(target_dir),
            "--passphrase",
            "demo-passphrase",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "Demo dataset created." in result.stdout
    assert (target_dir / "secrets.db").exists()
    assert (target_dir / "config.json").exists()

    config = json.loads((target_dir / "config.json").read_text(encoding="utf-8"))
    assert config["timeout_enabled"] is True

    storage = Storage(str(target_dir / "secrets.db"))
    vault_names = [item["name"] for item in storage.list_vaults()]
    assert vault_names == ["lab", "personal", "work"]

    lab_secret = storage.get_secret("lab", "registry-password")
    assert lab_secret["metadata"]["description"] == "Fake registry credential for screenshots"

    shutil.rmtree(target_dir)
