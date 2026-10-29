"""CSI native solver stability evidence; case completion is insufficient."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from struct_agent.io.artifacts import sha256


def solver_health(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding='utf-8',errors='replace')
    negative = [int(value) for value in re.findall(r'NUMBER OF NEGATIVE EIGENVALUES\s*=\s*(\d+)',text)]
    critical = [line.strip() for line in text.splitlines() if re.search(
        r'THE STRUCTURE IS UNSTABLE|ILL[- ]CONDITIONED\s*!!|NUMERICAL INSTABILITY|LOSS OF ACCURACY',line,re.I)]
    warnings = len(re.findall(r'W\s*A\s*R\s*N\s*I\s*N\s*G',text,re.I))
    return {'path':str(path),'sha256':sha256(path),'negative_eigenvalues':negative,
        'critical_messages':critical,'warning_markers':warnings,
        'verified':bool(negative) and all(n == 0 for n in negative) and not critical}
