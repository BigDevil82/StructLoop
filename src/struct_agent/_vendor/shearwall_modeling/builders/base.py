import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import openseespy.opensees as ops
from ..core.config import ModelConfig
from ..core.domain import BeamRole, FEMInput, PlanMember

@dataclass
class WallBaseCheckUnit:
    wall_id: int
    base_nodes: list[int]
    length: float
    thickness: float

@dataclass
class BeamElementUnit:
    beam_id: int
    story: int
    element_tag: int
    member: PlanMember
    role: BeamRole
    width: float
    depth: float
    length: float

@dataclass
class WallStoryElementUnit:
    wall_id: int
    story: int
    element_tags: list[int]
    bottom_nodes: list[int]
    top_nodes: list[int]
    node_coords: dict[int, tuple[float, float, float]]
    member: PlanMember
    thickness: float
    story_height: float
    source_wall_ids: tuple[int, ...] = ()

@dataclass
class ModelBuildResult:
    master_nodes: list[int]
    floor_area: float
    floor_load_masses: list[float]
    floor_self_masses: list[float]
    wall_base_units: list[WallBaseCheckUnit]
    floor_story_nodes: list[list[int]]
    beam_element_units: list[BeamElementUnit]
    wall_story_element_units: list[WallStoryElementUnit]
    wall_mesh_element_units: list[WallStoryElementUnit] = field(default_factory=list)

class StructuralModelBuilder(ABC):
    name: str

    @abstractmethod
    def build(self, input_data: FEMInput, config: ModelConfig) -> ModelBuildResult:
        raise NotImplementedError

@dataclass(frozen=True)
class AnalysisModelContext:
    build_result: ModelBuildResult
    config: ModelConfig
    logger: logging.Logger

    @property
    def master_nodes(self) -> list[int]:
        return self.build_result.master_nodes

    @property
    def floor_area(self) -> float:
        return self.build_result.floor_area

    @property
    def floor_load_masses(self) -> list[float]:
        return self.build_result.floor_load_masses

    @property
    def floor_self_masses(self) -> list[float]:
        return self.build_result.floor_self_masses

    @property
    def wall_base_units(self):
        return self.build_result.wall_base_units

    @property
    def beam_element_units(self):
        return self.build_result.beam_element_units

    @property
    def wall_story_element_units(self):
        return self.build_result.wall_story_element_units

    @property
    def floor_story_nodes(self) -> list[list[int]]:
        return self.build_result.floor_story_nodes

    @property
    def num_stories(self) -> int:
        return len(self.master_nodes)

    @property
    def story_heights(self) -> list[float]:
        return self.config.get_story_heights()

    @property
    def story_profiles(self):
        return self.config.resolve_story_profiles()

    @property
    def floor_masses(self) -> list[float]:
        return [ops.nodeMass(node, 1) for node in self.master_nodes]

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        nodes = ops.getNodeTags()
        xs = [ops.nodeCoord(node, 1) for node in nodes]
        ys = [ops.nodeCoord(node, 2) for node in nodes]
        return (min(xs), max(xs), min(ys), max(ys))
