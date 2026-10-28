import json
from pathlib import Path

import pytest
import torch

from struct_agent.adapters.casino_assets import prepare_context
from struct_agent.schemas import LayoutCandidate, RoomGraph


def test_layout_context_is_fresh_and_geometry_bound(tmp_path: Path,layout: LayoutCandidate,rooms: RoomGraph) -> None:
    a = prepare_context(layout,rooms,tmp_path/'a')
    moved = layout.members[0].model_copy(update={"start":(0.,4.),"end":(4.,4.)})
    alternate = layout.model_copy(update={"members":(moved,)})
    b = prepare_context(alternate,rooms,tmp_path/'b')
    assert a.name != b.name
    ga = torch.load(a.with_suffix('.pt'),weights_only=True)
    gb = torch.load(b.with_suffix('.pt'),weights_only=True)
    assert ga['x'].shape == (1,41)
    assert not torch.equal(ga['x'][:,25:],gb['x'][:,25:])
    with pytest.raises(FileExistsError):
        prepare_context(alternate,rooms,tmp_path/'a')


def test_migrated_runtime_has_no_old_source_imports() -> None:
    import ast
    manifest = json.loads(Path('src/struct_agent/_vendor/migration_manifest.json').read_text(encoding='utf-8'))
    for row in manifest['files']:
        tree = ast.parse(Path(row['destination']).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                assert not (node.module or '').startswith('src.')
                assert '.training.' not in (node.module or '')
