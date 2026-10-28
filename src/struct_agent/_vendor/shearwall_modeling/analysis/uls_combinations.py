from dataclasses import dataclass
from typing import Literal
from ..builders.base import AnalysisModelContext
from ..core.constants import concrete_fc_pa
LoadType = Literal['NonSeismic', 'Seismic']
ForceTuple = tuple[float, float, float]

@dataclass(frozen=True)
class LoadCombinationDef:
    name: str
    type: LoadType
    factors: dict[str, float]

@dataclass(frozen=True)
class MemberForceEnvelope:
    max_axial_n: float
    max_axial_combo: str
    max_moment_n_m: float
    max_moment_combo: str
    max_shear_n: float
    max_shear_combo: str

@dataclass(frozen=True)
class WallULSMetric:
    wall_id: int
    story: int
    length: float
    thickness: float
    axial_ratio: float
    axial_ratio_limit: float
    axial_control_combo: str
    is_axial_passed: bool
    shear_pressure_ratio: float
    shear_pressure_ratio_limit: float
    shear_control_combo: str
    shear_control_combo_type: LoadType
    is_shear_pressure_passed: bool

@dataclass(frozen=True)
class BeamULSMetric:
    beam_id: int
    story: int
    length: float
    shear_pressure_ratio: float
    shear_pressure_ratio_limit: float
    shear_control_combo: str
    shear_control_combo_type: LoadType
    is_shear_pressure_passed: bool

@dataclass(frozen=True)
class ULSCombinationResult:
    beam_forces_by_combo: dict[str, dict[tuple[int, int], ForceTuple]]
    wall_forces_by_combo: dict[str, dict[tuple[int, int], ForceTuple]]
    wall_metrics: list[WallULSMetric]
    beam_metrics: list[BeamULSMetric]
DEFAULT_COMBINATIONS: list[LoadCombinationDef] = [LoadCombinationDef(name='1.3D+1.5L', type='NonSeismic', factors={'Dead': 1.3, 'Live': 1.5}), LoadCombinationDef(name='1.3D+1.05L+1.5WX', type='NonSeismic', factors={'Dead': 1.3, 'Live': 1.05, 'WindX': 1.5}), LoadCombinationDef(name='1.3D+1.05L-1.5WX', type='NonSeismic', factors={'Dead': 1.3, 'Live': 1.05, 'WindX': -1.5}), LoadCombinationDef(name='1.3D+1.05L+1.5WY', type='NonSeismic', factors={'Dead': 1.3, 'Live': 1.05, 'WindY': 1.5}), LoadCombinationDef(name='1.3D+1.05L-1.5WY', type='NonSeismic', factors={'Dead': 1.3, 'Live': 1.05, 'WindY': -1.5}), LoadCombinationDef(name='1.2G+1.3EX', type='Seismic', factors={'Dead': 1.2, 'Live': 0.6, 'EqX': 1.3}), LoadCombinationDef(name='1.2G-1.3EX', type='Seismic', factors={'Dead': 1.2, 'Live': 0.6, 'EqX': -1.3}), LoadCombinationDef(name='1.2G+1.3EY', type='Seismic', factors={'Dead': 1.2, 'Live': 0.6, 'EqY': 1.3}), LoadCombinationDef(name='1.2G-1.3EY', type='Seismic', factors={'Dead': 1.2, 'Live': 0.6, 'EqY': -1.3})]

class ULSCombinationAnalyzer:
    """Combine basic case effects and extract ULS envelopes for members.

    Notes:
    - Basic case effects are passed in as per-member force dictionaries.
    - Force tuples in current analysis pipeline are unsigned effect envelopes.
      For safety, this analyzer uses abs(factor) weighted summation.
    - Missing basic cases are treated as zero effects.
    """

    def __init__(self, context: AnalysisModelContext, combinations: list[LoadCombinationDef] | None=None, beta_c: float=1.0):
        self.context = context
        self.combinations = combinations or DEFAULT_COMBINATIONS
        self.beta_c = beta_c
        self.combo_type_by_name = {item.name: item.type for item in self.combinations}

    def run(self, beam_case_forces: dict[str, dict[tuple[int, int], ForceTuple]], wall_case_forces: dict[str, dict[tuple[int, int], ForceTuple]]) -> ULSCombinationResult:
        beam_combo_forces, wall_combo_forces = self._combine_all(beam_case_forces, wall_case_forces)
        beam_envelope = self._build_envelope(beam_combo_forces)
        wall_envelope = self._build_envelope(wall_combo_forces)
        wall_metrics = self._collect_wall_metrics(wall_envelope, wall_combo_forces)
        beam_metrics = self._collect_beam_metrics(beam_envelope)
        return ULSCombinationResult(beam_forces_by_combo=beam_combo_forces, wall_forces_by_combo=wall_combo_forces, wall_metrics=wall_metrics, beam_metrics=beam_metrics)

    def _combine_all(self, beam_case_forces: dict[str, dict[tuple[int, int], ForceTuple]], wall_case_forces: dict[str, dict[tuple[int, int], ForceTuple]]) -> tuple[dict[str, dict[tuple[int, int], ForceTuple]], dict[str, dict[tuple[int, int], ForceTuple]]]:
        beam_keys = {key for item in beam_case_forces.values() for key in item}
        wall_keys = {key for item in wall_case_forces.values() for key in item}
        beam_combo_forces: dict[str, dict[tuple[int, int], ForceTuple]] = {}
        wall_combo_forces: dict[str, dict[tuple[int, int], ForceTuple]] = {}
        for combo in self.combinations:
            beam_combo_forces[combo.name] = {key: self._combine_one_force(key, combo, beam_case_forces) for key in beam_keys}
            wall_combo_forces[combo.name] = {key: self._combine_one_force(key, combo, wall_case_forces) for key in wall_keys}
        return (beam_combo_forces, wall_combo_forces)

    def _combine_one_force(self, key: tuple[int, int], combo: LoadCombinationDef, case_forces: dict[str, dict[tuple[int, int], ForceTuple]]) -> ForceTuple:
        v0, v1, v2 = (0.0, 0.0, 0.0)
        for case_name, factor in combo.factors.items():
            item = case_forces.get(case_name, {})
            a0, a1, a2 = item.get(key, (0.0, 0.0, 0.0))
            scale = abs(float(factor))
            v0 += scale * float(a0)
            v1 += scale * float(a1)
            v2 += scale * float(a2)
        return (v0, v1, v2)

    def _build_envelope(self, combo_forces: dict[str, dict[tuple[int, int], ForceTuple]]) -> dict[tuple[int, int], MemberForceEnvelope]:
        keys = {key for item in combo_forces.values() for key in item}
        envelope: dict[tuple[int, int], MemberForceEnvelope] = {}
        for key in keys:
            axial_max = -1.0
            axial_combo = ''
            moment_max = -1.0
            moment_combo = ''
            shear_max = -1.0
            shear_combo = ''
            for combo_name, forces in combo_forces.items():
                axial_n, moment_n_m, shear_n = forces.get(key, (0.0, 0.0, 0.0))
                if axial_n > axial_max:
                    axial_max = axial_n
                    axial_combo = combo_name
                if moment_n_m > moment_max:
                    moment_max = moment_n_m
                    moment_combo = combo_name
                if shear_n > shear_max:
                    shear_max = shear_n
                    shear_combo = combo_name
            envelope[key] = MemberForceEnvelope(max_axial_n=max(axial_max, 0.0), max_axial_combo=axial_combo, max_moment_n_m=max(moment_max, 0.0), max_moment_combo=moment_combo, max_shear_n=max(shear_max, 0.0), max_shear_combo=shear_combo)
        return envelope

    def _collect_wall_metrics(self, wall_envelope: dict[tuple[int, int], MemberForceEnvelope], wall_combo_forces: dict[str, dict[tuple[int, int], ForceTuple]]) -> list[WallULSMetric]:
        story_profiles = {profile.story: profile for profile in self.context.story_profiles}
        metrics: list[WallULSMetric] = []
        for unit in self.context.wall_story_element_units:
            key = (unit.wall_id, unit.story)
            if key not in wall_envelope:
                continue
            envelope = wall_envelope[key]
            concrete_grade = story_profiles[unit.story].material.concrete_grade
            fc_pa = concrete_fc_pa(concrete_grade)
            area_m2 = max(unit.member.length * unit.thickness, 1e-09)
            axial_n, axial_combo = self._select_axial_for_wall(key, wall_combo_forces)
            axial_ratio = axial_n / (fc_pa * area_m2)
            axial_limit = self.context.config.seismic.axial_compression_ratio_limit
            b = max(unit.thickness, 1e-09)
            h0 = max(unit.member.length, 1e-09)
            denom = max(self.beta_c * fc_pa * b * h0, 1e-09)
            shear_ratio = envelope.max_shear_n / denom
            shear_combo_type = self.combo_type_by_name.get(envelope.max_shear_combo, 'NonSeismic')
            shear_limit = 0.15 if shear_combo_type == 'Seismic' else 0.2
            metrics.append(WallULSMetric(wall_id=unit.wall_id, story=unit.story, length=unit.member.length, thickness=unit.thickness, axial_ratio=axial_ratio, axial_ratio_limit=axial_limit, axial_control_combo=axial_combo, is_axial_passed=axial_ratio <= axial_limit, shear_pressure_ratio=shear_ratio, shear_pressure_ratio_limit=shear_limit, shear_control_combo=envelope.max_shear_combo, shear_control_combo_type=shear_combo_type, is_shear_pressure_passed=shear_ratio <= shear_limit))
        return metrics

    def _select_axial_for_wall(self, key: tuple[int, int], wall_combo_forces: dict[str, dict[tuple[int, int], ForceTuple]]) -> tuple[float, str]:
        seismic_candidates: list[tuple[str, float]] = []
        nonseismic_candidates: list[tuple[str, float]] = []
        for combo_name, forces in wall_combo_forces.items():
            axial_n = abs(forces.get(key, (0.0, 0.0, 0.0))[0])
            combo_type = self.combo_type_by_name.get(combo_name, 'NonSeismic')
            if combo_type == 'Seismic':
                seismic_candidates.append((combo_name, axial_n))
            else:
                nonseismic_candidates.append((combo_name, axial_n))
        source = seismic_candidates if seismic_candidates else nonseismic_candidates
        if not source:
            return (0.0, '')
        combo_name, axial_n = max(source, key=lambda item: item[1])
        return (axial_n, combo_name)

    def _collect_beam_metrics(self, beam_envelope: dict[tuple[int, int], MemberForceEnvelope]) -> list[BeamULSMetric]:
        story_profiles = {profile.story: profile for profile in self.context.story_profiles}
        metrics: list[BeamULSMetric] = []
        for unit in self.context.beam_element_units:
            key = (unit.beam_id, unit.story)
            envelope = beam_envelope.get(key)
            if envelope is None:
                continue
            concrete_grade = story_profiles[unit.story].material.concrete_grade
            fc_pa = concrete_fc_pa(concrete_grade)
            b = max(unit.width, 1e-09)
            h0 = max(unit.depth, 1e-09)
            denom = max(self.beta_c * fc_pa * b * h0, 1e-09)
            shear_ratio = envelope.max_shear_n / denom
            shear_combo_type = self.combo_type_by_name.get(envelope.max_shear_combo, 'NonSeismic')
            shear_limit = 0.15 if shear_combo_type == 'Seismic' else 0.2
            metrics.append(BeamULSMetric(beam_id=unit.beam_id, story=unit.story, length=unit.length, shear_pressure_ratio=shear_ratio, shear_pressure_ratio_limit=shear_limit, shear_control_combo=envelope.max_shear_combo, shear_control_combo_type=shear_combo_type, is_shear_pressure_passed=shear_ratio <= shear_limit))
        return metrics
