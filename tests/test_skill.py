import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / ".agents" / "skills" / "curate-aroma-data"


def test_skill_metadata_and_interface_are_complete():
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    interface = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: curate-aroma-data\n")
    assert "TODO" not in skill
    assert "description:" in skill.split("---", 2)[1]
    assert 'display_name: "Curate Aroma Data"' in interface
    assert "$curate-aroma-data" in interface


def test_skill_inspector_reports_identifier_quality(tmp_path: Path):
    workbook = tmp_path / "input.xlsx"
    pd.DataFrame({"CAS Number": ["100-52-7", "", "100-52-8"]}).to_excel(workbook, index=False)
    script = SKILL_ROOT / "scripts" / "inspect_workbook.py"
    completed = subprocess.run(
        [sys.executable, str(script), str(workbook)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    assert report["rows"] == 3
    assert report["cas"]["valid"] == 1
    assert report["cas"]["invalid"] == 1
