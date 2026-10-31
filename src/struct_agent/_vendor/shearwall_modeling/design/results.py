from dataclasses import dataclass, field
from ..geometry.wall_piers import CompoundWallSection

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
    moment_cases: tuple[tuple[float, float, bool], ...] = ()
    shear_cases: tuple[tuple[float, float, bool], ...] = ()
    coupling: bool = False

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
    # N compression positive, M in N*m, V in N, section ratio limit, seismic.
    load_cases: tuple[tuple[float, float, float, float, bool], ...] = ()
    seismic: bool = False
    shear_limit: float = .20


@dataclass(frozen=True)
class CompoundWallDesignDemand:
    section: CompoundWallSection
    # label, N (compression positive), Mx/My (N*m), seismic.
    load_cases: tuple[tuple[str,float,float,float,bool], ...]
    axial_limit: float


@dataclass(frozen=True)
class SectionEquilibrium:
    combination: str
    target_n_mx_my: tuple[float,float,float]
    resultant_n_mx_my: tuple[float,float,float]
    relative_error: float
    max_concrete_strain: float
    min_steel_strain: float
    passed: bool


@dataclass(frozen=True)
class CompoundWallReinforcementResult:
    section_id: int
    story: int
    wall_ids: tuple[int,...]
    kind: str
    centroid_m: tuple[float,float]
    area_m2: float
    boundary_area_m2: float
    longitudinal_steel_mm2: float
    boundary_ratio: float
    distributed_ratio: float
    axial_ratio: float
    axial_limit: float
    is_passed: bool
    checks: tuple[SectionEquilibrium,...]
    messages: tuple[str,...]

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
    compound_section_id: int | None = None
    shared_wall_ids: tuple[int,...] = ()

    @property
    def is_passed(self) -> bool:
        return not self.is_over_reinforced and (not self.is_section_insufficient)

@dataclass
class ReinforcementDesignSummary:
    beam_results: list[BeamReinforcementResult]
    wall_results: list[WallReinforcementResult]
    compound_results: list[CompoundWallReinforcementResult] = field(default_factory=list)

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
        return not self.failed_beams and not self.failed_walls and all(r.is_passed for r in self.compound_results)
