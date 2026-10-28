"""A four-room, two-layout fixture independent of model weights or commercial data."""
from __future__ import annotations

from struct_agent.schemas import DesignCandidate, DesignVariable, LayoutCandidate, Member, ProjectSpec
from struct_agent.schemas.state import MockCase


def make_mock_case() -> MockCase:
    """Layout A lacks a Y wall; layout B becomes mock-feasible with thicker walls."""
    variables = (
        DesignVariable(name="tw_bot", unit="m", values=(0.2, 0.3)),
        DesignVariable(name="tw_mid", unit="m", values=(0.16,)),
        DesignVariable(name="tw_top", unit="m", values=(0.16,)),
        DesignVariable(name="hb_main", unit="m", values=(0.5,)),
        DesignVariable(name="bb_main", unit="m", values=(0.2,)),
        DesignVariable(name="hb_sec", unit="m", values=(0.3,)),
        DesignVariable(name="bb_sec", unit="m", values=(0.2,)),
        DesignVariable(name="conc_bot", unit="grade", values=("C30",)),
    )
    spec = ProjectSpec(condition_id="synthetic_only", stories=28, story_height_m=2.9,
        slab_thickness_m=0.12, intensity=8.0, site_class="II", seismic_group=1,
        objective="upstream_material_cost_cny", code_basis="MOCK ONLY: no engineering code check",
        design_variables=variables)
    slabs = tuple(((x, y), (x + 4.0, y), (x + 4.0, y + 4.0), (x, y + 4.0))
                  for y in (0.0, 4.0) for x in (0.0, 4.0))
    wall_x = Member(member_id="wx", start=(0.0, 0.0), end=(8.0, 0.0), role="wall")
    wall_y = Member(member_id="wy", start=(0.0, 0.0), end=(0.0, 8.0), role="wall")
    layouts = tuple(LayoutCandidate(layout_id=name, source="synthetic_state_machine_fixture",
        length_unit="m", coordinate_system="global_xy", members=members, slabs=slabs)
        for name, members in (("layout_a", (wall_x,)), ("layout_b", (wall_x, wall_y))))
    base = {variable.name: variable.values[0] for variable in variables}
    designs = tuple(DesignCandidate(design_id=f"{layout.layout_id}_{index}",
        layout_id=layout.layout_id, condition_id=spec.condition_id,
        values={**base, "tw_bot": thickness})
        for layout in layouts for index, thickness in enumerate((0.2, 0.3)))
    return MockCase(case_id="toy_01", fidelity="mock", scenario="directional_capacity_v1",
        spec=spec, layouts=layouts, designs=designs, initial_layout_id="layout_a")
