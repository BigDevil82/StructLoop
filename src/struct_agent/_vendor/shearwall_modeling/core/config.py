from dataclasses import dataclass, field
from typing import Optional
from .constants import CONCRETE_ELASTIC_MODULUS_MPA, GB50011_TG_BY_SITE_CLASS, SEISMIC_ALPHA_MAX_BY_INTENSITY
from .domain import BeamRole

def _normalize_concrete_grade(concrete_grade: str) -> str:
    """Normalize a concrete grade string like `30` or `c30` to `C30`."""
    grade = concrete_grade.strip().upper()
    if not grade.startswith('C'):
        grade = f'C{grade}'
    if grade not in CONCRETE_ELASTIC_MODULUS_MPA:
        supported = ', '.join(sorted(CONCRETE_ELASTIC_MODULUS_MPA.keys()))
        raise ValueError(f'Unsupported concrete_grade={concrete_grade}. Supported grades: {supported}')
    return grade

def _resolve_elastic_modulus_pa(concrete_grade: str) -> float:
    grade = _normalize_concrete_grade(concrete_grade)
    return CONCRETE_ELASTIC_MODULUS_MPA[grade] * 1000000.0

def _resolve_shear_modulus_pa(elastic_modulus_pa: float, poisson_ratio: float=0.2) -> float:
    if poisson_ratio <= -1.0:
        raise ValueError('poisson_ratio must be greater than -1.')
    return elastic_modulus_pa / (2.0 * (1.0 + poisson_ratio))

def _gb50011_spectrum_shape_params(damping_ratio: float) -> tuple[float, float, float]:
    xi = damping_ratio
    gamma = 0.9 + (0.05 - xi) / (0.3 + 6.0 * xi)
    eta1 = 0.02 + (0.05 - xi) / (4.0 + 32.0 * xi)
    eta2 = 1.0 + (0.05 - xi) / (0.08 + 1.6 * xi)
    eta1 = max(0.0, eta1)
    eta2 = min(1.0, max(0.55, eta2))
    return (gamma, eta1, eta2)

def _calculate_gb50011_alpha(period: float, alpha_max: float, characteristic_period: float, damping_ratio: float) -> float:
    """Calculate the GB50011 seismic influence coefficient for a vibration period."""
    gamma, eta1, eta2 = _gb50011_spectrum_shape_params(damping_ratio)
    if period <= 0.1:
        return alpha_max * (0.45 + (eta2 - 0.45) * (period / 0.1))
    if period <= characteristic_period:
        return eta2 * alpha_max
    if period <= 5.0 * characteristic_period:
        return eta2 * alpha_max * (characteristic_period / period) ** gamma
    if period <= 6.0:
        return alpha_max * (eta2 * 0.2 ** gamma - eta1 * (period - 5.0 * characteristic_period))
    return alpha_max * max(0.0, eta2 * 0.2 ** gamma - eta1 * (6.0 - 5.0 * characteristic_period))

def _resolve_gb50011_design_params(intensity: float, site_class: str, seismic_group: int, alpha_max_override: Optional[float], Tg_override: Optional[float]) -> tuple[float, float]:
    acc_key = round(float(intensity), 2)
    site_key = str(site_class).upper()
    group_key = int(seismic_group)
    if alpha_max_override is None:
        if acc_key not in SEISMIC_ALPHA_MAX_BY_INTENSITY:
            raise ValueError(f'Unsupported intensity={intensity}. Set alpha_max_override to continue.')
        alpha_max = SEISMIC_ALPHA_MAX_BY_INTENSITY[acc_key]
    else:
        alpha_max = float(alpha_max_override)
    if Tg_override is None:
        if site_key not in GB50011_TG_BY_SITE_CLASS or group_key not in GB50011_TG_BY_SITE_CLASS[site_key]:
            raise ValueError(f'Unsupported site/group combination: site_class={site_class}, seismic_group={seismic_group}. Set Tg_override to continue.')
        tg = GB50011_TG_BY_SITE_CLASS[site_key][group_key]
    else:
        tg = float(Tg_override)
    return (alpha_max, tg)

def _build_gb50011_response_spectrum(alpha_max: float, characteristic_period: float, damping_ratio: float, gravity: float, t_max: float, dt: float) -> tuple[list[float], list[float]]:
    if dt <= 0.0:
        raise ValueError('spectrum_dt must be greater than 0.')
    if t_max <= 0.0:
        raise ValueError('spectrum_t_max must be greater than 0.')
    periods: list[float] = []
    spectral_accel: list[float] = []
    steps = int(t_max / dt)
    for i in range(steps + 1):
        t = i * dt
        alpha = _calculate_gb50011_alpha(t, alpha_max, characteristic_period, damping_ratio=damping_ratio)
        periods.append(t)
        spectral_accel.append(alpha * gravity)
    return (periods, spectral_accel)

@dataclass(frozen=True)
class ResponseSpectrum:
    periods: list[float]
    spectral_accel: list[float]

class ResponseSpectrumBuilder:
    """Build response spectra from seismic configuration values."""

    def build(self, config: 'SeismicConfig') -> ResponseSpectrum:
        if config.design_code.upper() != 'GB50011':
            raise ValueError(f'Unsupported design_code={config.design_code}. Currently only GB50011 is implemented.')
        alpha_max, characteristic_period = _resolve_gb50011_design_params(intensity=config.intensity, site_class=config.site_class, seismic_group=config.seismic_group, alpha_max_override=config.alpha_max_override, Tg_override=config.Tg_override)
        periods, spectral_accel = _build_gb50011_response_spectrum(alpha_max=alpha_max, characteristic_period=characteristic_period, damping_ratio=config.damping_ratio, gravity=config.gravity, t_max=config.spectrum_t_max, dt=config.spectrum_dt)
        return ResponseSpectrum(periods=periods, spectral_accel=spectral_accel)

@dataclass
class MaterialConfig:
    concrete_grade: str = 'C40'
    E: Optional[float] = None
    G: Optional[float] = None
    density_kg_m3: float = 2550.0

    def __post_init__(self) -> None:
        self.concrete_grade = _normalize_concrete_grade(self.concrete_grade)
        if self.E is None:
            self.E = _resolve_elastic_modulus_pa(self.concrete_grade)
        if self.G is None:
            self.G = _resolve_shear_modulus_pa(self.E)

@dataclass
class SectionConfig:
    wall_thickness: float = 0.2
    beam_width: float = 0.3
    beam_depth: float = 0.5
    secondary_beam_width: Optional[float] = None
    secondary_beam_depth: Optional[float] = None
    slab_thickness: float = 0.12

    def get_beam_section(self, role: BeamRole) -> tuple[float, float]:
        if role == BeamRole.SECONDARY:
            width = self.beam_width if self.secondary_beam_width is None else self.secondary_beam_width
            depth = self.beam_depth if self.secondary_beam_depth is None else self.secondary_beam_depth
            return (width, depth)
        return (self.beam_width, self.beam_depth)

@dataclass
class SeismicConfig:
    periods: list[float] = field(default_factory=list)
    sa: list[float] = field(default_factory=list)
    damping_ratio: float = 0.05
    combination_method: str = 'CQC'
    design_code: str = 'GB50011'
    intensity: float = 7.0
    site_class: str = 'II'
    seismic_group: int = 1
    alpha_max_override: Optional[float] = None
    Tg_override: Optional[float] = None
    spectrum_t_max: float = 6.0
    spectrum_dt: float = 0.01
    gravity: float = 9.81
    axial_compression_ratio_limit: float = 0.5

    def __post_init__(self) -> None:
        if self.periods and self.sa:
            return
        if self.periods or self.sa:
            raise ValueError('seismic.periods and seismic.sa should be both provided or both omitted.')
        spectrum = ResponseSpectrumBuilder().build(self)
        self.periods = spectrum.periods
        self.sa = spectrum.spectral_accel

    @property
    def spectral_accel(self) -> list[float]:
        return self.sa

@dataclass
class MassSourceConfig:
    dead_kpa: float = 5.0
    live_kpa: float = 2.0
    dead_factor: float = 1.0
    live_factor: float = 0.5
    include_structural_self_weight: bool = True
    gravity: float = 9.81

    def load_to_mass_per_area(self) -> float:
        source_kpa = self.dead_factor * self.dead_kpa + self.live_factor * self.live_kpa
        return source_kpa * 1000.0 / self.gravity

@dataclass
class ModelConfig:
    standard_story_groups: list['StandardStoryGroupConfig']
    mass_source: MassSourceConfig = field(default_factory=MassSourceConfig)
    material: MaterialConfig = field(default_factory=MaterialConfig)
    section: SectionConfig = field(default_factory=SectionConfig)
    seismic: SeismicConfig = field(default_factory=SeismicConfig)
    num_modes: int = 12

    def __post_init__(self) -> None:
        if not self.standard_story_groups:
            raise ValueError('standard_story_groups is required and cannot be empty.')
        for group in self.standard_story_groups:
            if group.count <= 0:
                raise ValueError('standard_story_groups.count must be greater than 0.')
            if group.story_height <= 0.0:
                raise ValueError('standard_story_groups.story_height must be greater than 0.')

    @property
    def num_stories(self) -> int:
        return sum((group.count for group in self.standard_story_groups))

    def resolve_story_profiles(self) -> list['StoryProfile']:
        profiles: list[StoryProfile] = []
        z_bottom = 0.0
        story_idx = 1
        for group in self.standard_story_groups:
            section = group.section or self.section
            mass_source = group.mass_source or self.mass_source
            material = group.material or self.material
            story_height = group.story_height
            for _ in range(group.count):
                z_top = z_bottom + story_height
                profiles.append(StoryProfile(story=story_idx, story_height=story_height, z_bottom=z_bottom, z_top=z_top, section=section, material=material, mass_source=mass_source))
                z_bottom = z_top
                story_idx += 1
        return profiles

    def get_story_heights(self) -> list[float]:
        return [profile.story_height for profile in self.resolve_story_profiles()]

@dataclass
class StandardStoryGroupConfig:
    count: int
    story_height: float
    section: Optional[SectionConfig] = None
    material: Optional[MaterialConfig] = None
    mass_source: Optional[MassSourceConfig] = None

@dataclass
class StoryProfile:
    story: int
    story_height: float
    z_bottom: float
    z_top: float
    section: SectionConfig
    material: MaterialConfig
    mass_source: MassSourceConfig
