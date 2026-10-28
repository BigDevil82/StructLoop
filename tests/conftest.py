from pathlib import Path

import pytest

from struct_agent.schemas import DesignCandidate, LayoutCandidate, Member, ProjectSpec, RoomGraph


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-real", action="store_true", help="Enable local-weight/OpenSees tests")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not config.getoption("--run-real"):
        for item in items:
            if "real" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Use --run-real to explicitly execute local-weight tests"))


@pytest.fixture
def spec() -> ProjectSpec:
    return ProjectSpec.model_validate_json(Path("configs/reference_spec.json").read_text(encoding="utf-8"))


@pytest.fixture
def layout() -> LayoutCandidate:
    return LayoutCandidate(layout_id="synthetic_unit_only", source="synthetic_test", length_unit="m",
        coordinate_system="global_xy", members=(Member(member_id="wall_0",start=(0.,0.),end=(4.,0.),role="wall"),),
        slabs=(((0.,0.),(4.,0.),(4.,4.),(0.,4.)),))


@pytest.fixture
def design(spec: ProjectSpec, layout: LayoutCandidate) -> DesignCandidate:
    return DesignCandidate(design_id="synthetic_design", layout_id=layout.layout_id, condition_id=spec.condition_id,
        values={v.name:v.values[0] for v in spec.design_variables})


@pytest.fixture
def rooms() -> RoomGraph:
    return RoomGraph(feature_version="rcgnn_25_8_v1",length_unit="m",native_feature_length_unit="mm",
        coordinate_system="global_xy", x=((0.,)*9+(1.,)*16,),edge_index=((),()),edge_attr=(),
        room_polygons=(((0.,0.),(4.,0.),(4.,4.),(0.,4.),(0.,0.)),),
        masks=(tuple((((0.,1.),)) for _ in range(8)),), category=0)
