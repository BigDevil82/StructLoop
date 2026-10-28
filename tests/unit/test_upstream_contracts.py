from pathlib import Path

from scripts.audit_upstream import inspect_source, report


def test_missing_source_is_blocked(tmp_path: Path) -> None:
    rows = inspect_source(tmp_path)
    assert all(r["status"] == "BLOCKED" for r in rows)
    assert "UNKNOWN" in report(tmp_path)


def test_audit_records_content_hash(tmp_path: Path) -> None:
    path = tmp_path / "src/shearwall_pred/model.py"
    path.parent.mkdir(parents=True)
    path.write_text("class Model: pass\n", encoding="utf-8")
    row = inspect_source(tmp_path)[0]
    assert row["status"] == "KNOWN"
    assert len(row["sha256"]) == 64
    assert row["symbols"] == ["Model"]
