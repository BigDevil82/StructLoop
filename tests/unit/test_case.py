import hashlib
import json
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

from struct_agent.io.case import load_generation_case
from struct_agent.cli import load_assets, main


def test_case_loader_checks_input_identity(tmp_path: Path) -> None:
    drawing = tmp_path / "input.dxf"
    drawing.write_bytes(b"fixture drawing bytes")
    payload = json.loads(Path("configs/test_case.json").read_text(encoding="utf-8"))
    payload.update(dxf=drawing.as_posix(), sha256=hashlib.sha256(drawing.read_bytes()).hexdigest())
    config = tmp_path / "case.json"
    config.write_text(json.dumps(payload), encoding="utf-8")
    case, actual = load_generation_case(config)
    assert actual == drawing and case.category == 2 and case.native_coordinate_unit == "mm"
    drawing.write_bytes(b"changed input")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        load_generation_case(config)
    drawing.unlink()
    with pytest.raises(FileNotFoundError, match="BLOCKED"):
        load_generation_case(config)


def test_case_rejects_implicit_unit_change(tmp_path: Path) -> None:
    payload = json.loads(Path("configs/test_case.json").read_text(encoding="utf-8"))
    payload["native_coordinate_unit"] = "m"
    config = tmp_path / "case.json"
    config.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_generation_case(config)


def test_weight_loading_does_not_require_historical_drawings(tmp_path: Path) -> None:
    weight = tmp_path / "weight.pt"
    weight.write_bytes(b"hash-check fixture; not a real model")
    config = tmp_path / "assets.json"
    config.write_text(json.dumps({
        "rc_fold_0": {"path": str(weight), "sha256": hashlib.sha256(weight.read_bytes()).hexdigest()},
        "reference_dxf": {"path": "missing_historical_case.dxf", "sha256": "0" * 64},
    }), encoding="utf-8")
    assert load_assets(config, names=("rc_fold_0",)) == {"rc_fold_0": weight}
    with pytest.raises(ValueError, match="missing rc_fold_1"):
        load_assets(config, names=("rc_fold_1",))


@pytest.mark.parametrize(("arguments", "expected"), [
    (["--help"], ("generate", "optimize")),
    (["generate", "--help"], ("--dxf", "--category", "--case-config", "--assets", "--run", "--seed")),
    (["optimize", "--help"], ("--layout", "--rooms", "--spec", "--budget-fea",
                              "--initial-design", "--generations-per-step", "--use-surrogate")),
])
def test_cli_keeps_real_commands(arguments: list[str], expected: tuple[str, ...],
                                monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["structloop", *arguments])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert all(option in output for option in expected)
    assert "run-case" not in output and "--approve-mock-layout" not in output


def test_cli_rejects_removed_mock_workflow(monkeypatch: pytest.MonkeyPatch,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["structloop", "run-case"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "invalid choice: 'run-case'" in capsys.readouterr().err
