"""Fingerprint the only current analysis implementation; no legacy solver modes."""
from __future__ import annotations

import hashlib
from pathlib import Path


def analysis_signature() -> str:
    root = Path(__file__).resolve().parents[1]
    files = sorted((root / '_vendor/shearwall_modeling').rglob('*.py'))
    files += [root / ('adapters/'+name) for name in ('fea.py', 'fea_diagnostics.py', 'fea_member_evidence.py')]
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).replace('\\', '/').encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
