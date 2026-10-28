from dataclasses import dataclass, field

@dataclass(frozen=True)
class BeamDesignDemand:
    beam_id: int
    story: int
    width_m: float
    depth_m: float
    length_m: float
    positive_moment_n_m: float
    negative_moment_n_m: float
    shear_n: float

@dataclass(frozen=True)
class WallDesignDemand:
    wall_id: int
    story: int
    thickness_m: float
    length_m: float
    story_height_m: float
    axial_force_n: float
    moment_n_m: float
    shear_n: float
    axial_ratio: float
    is_bottom_reinforced_zone: bool

@dataclass(frozen=True)
class MaterialUsage:
    concrete_kg: float
    steel_kg: float

    @property
    def total_kg(self) -> float:
        return self.concrete_kg + self.steel_kg

@dataclass
class BeamReinforcementResult:
    beam_id: int
    story: int
    top_steel_area_mm2: float
    bottom_steel_area_mm2: float
    stirrup_area_per_spacing_mm2_per_mm: float
    stirrup_spacing_mm: float
    material_usage: MaterialUsage
    is_over_reinforced: bool
    is_section_insufficient: bool
    messages: list[str] = field(default_factory=list)

    @property
    def is_passed(self) -> bool:
        return not self.is_over_reinforced and (not self.is_section_insufficient)

@dataclass
class WallReinforcementResult:
    wall_id: int
    story: int
    vertical_distributed_steel_mm2_per_m: float
    horizontal_distributed_steel_mm2_per_m: float
    boundary_longitudinal_steel_mm2: float
    boundary_stirrup_area_mm2: float
    boundary_stirrup_spacing_mm: float
    boundary_type: str
    material_usage: MaterialUsage
    is_over_reinforced: bool
    is_section_insufficient: bool
    messages: list[str] = field(default_factory=list)

    @property
    def is_passed(self) -> bool:
        return not self.is_over_reinforced and (not self.is_section_insufficient)

@dataclass
class ReinforcementDesignSummary:
    beam_results: list[BeamReinforcementResult]
    wall_results: list[WallReinforcementResult]

    @property
    def total_concrete_kg(self) -> float:
        return sum((item.material_usage.concrete_kg for item in self.beam_results)) + sum((item.material_usage.concrete_kg for item in self.wall_results))

    @property
    def total_steel_kg(self) -> float:
        return sum((item.material_usage.steel_kg for item in self.beam_results)) + sum((item.material_usage.steel_kg for item in self.wall_results))

    @property
    def failed_beams(self) -> list[BeamReinforcementResult]:
        return [item for item in self.beam_results if not item.is_passed]

    @property
    def failed_walls(self) -> list[WallReinforcementResult]:
        return [item for item in self.wall_results if not item.is_passed]

    @property
    def is_passed(self) -> bool:
        return not self.failed_beams and (not self.failed_walls)
