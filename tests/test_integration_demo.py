import json
import subprocess
from pathlib import Path


def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True)
    assert p.returncode == 0, (
        f"command failed: {' '.join(cmd)}\n"
        f"stdout:\n{p.stdout}\n"
        f"stderr:\n{p.stderr}"
    )


def test_end_to_end_demo(tmp_path: Path) -> None:
    policy = "examples/configs/policy_min.json"
    features = "examples/configs/features_min.json"
    plan = tmp_path / "plan.json"
    sql = tmp_path / "query.sql"

    _run(["ppds", "validate", "--policy", policy, "--features", features])
    _run(["ppds", "plan", "--policy", policy, "--features", features, "--out", str(plan)])
    _run(["ppds", "emit-sql", "--plan", str(plan), "--dialect", "spark", "--out", str(sql)])

    obj = json.loads(plan.read_text(encoding="utf-8"))
    assert "decision" in obj
    assert "boundary" in obj["decision"]
    assert "granularity" in obj["decision"]
    assert sql.read_text(encoding="utf-8").strip() != ""
