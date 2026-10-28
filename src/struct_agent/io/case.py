"""Load a drawing reference and verify its bytes before model inference."""
from pathlib import Path

from struct_agent.io.artifacts import sha256
from struct_agent.schemas.case import GenerationCase


def load_generation_case(path: Path) -> tuple[GenerationCase, Path]:
    """DXF path is project-root-relative, consistent with the local asset manifest."""
    case = GenerationCase.model_validate_json(path.read_text(encoding="utf-8"))
    drawing = Path(case.dxf)
    if not drawing.is_file():
        raise FileNotFoundError(f"BLOCKED: case {case.case_id} drawing missing: {drawing}")
    if sha256(drawing) != case.sha256:
        raise ValueError(f"Case {case.case_id} drawing SHA256 mismatch: {drawing}")
    return case, drawing
