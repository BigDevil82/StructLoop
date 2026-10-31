import logging
from itertools import product
from ..analysis.results import AnalysisResult
from ..builders.base import ModelBuildResult
from ..core.config import ModelConfig
from .constants import CONCRETE_COMPRESSIVE_STRENGTH_MPA
from .results import BeamDesignDemand, WallDesignDemand, CompoundWallDesignDemand
from ..analysis.uls_combinations import DEFAULT_COMBINATIONS
from ..geometry.wall_piers import compound_wall_sections

class DesignDemandExtractor:

    def __init__(self, build_result: ModelBuildResult, config: ModelConfig, logger: logging.Logger):
        self.build_result = build_result
        self.config = config
        self.logger = logger

    def extract(self, analysis_result: AnalysisResult) -> tuple[list[BeamDesignDemand], list[WallDesignDemand]]:
        self.beam_checks = {(m.beam_id,m.story):m for m in analysis_result.beam_uls_metrics}
        self.wall_checks = {(m.wall_id,m.story):m for m in analysis_result.wall_uls_metrics}
        self.seismic_combos = {c.name for c in DEFAULT_COMBINATIONS if c.type == 'Seismic'}
        combined_beams = self._combine_beam_demands(analysis_result.beam_forces_by_combo)
        combined_walls = self._combine_wall_demands(analysis_result.wall_forces_by_combo)
        self.compound_demands=[]
        for section in compound_wall_sections(self.build_result.wall_story_element_units):
            key=(section.section_id,section.story)
            cases=[]
            for combo in DEFAULT_COMBINATIONS:
                seismic=combo.type=='Seismic'
                quake=[name for name in combo.factors if name.startswith('Eq')]
                if seismic:
                    name=quake[0];factor=combo.factors[name]
                    if factor<0:continue  # The full component-sign envelope includes both directions.
                    base=[sum(f*analysis_result.compound_forces_by_case[c][key][i]
                        for c,f in combo.factors.items() if c!=name) for i in range(3)]
                    amplitude=analysis_result.compound_forces_by_case[name][key]
                    # CQC components are peak amplitudes, not a concurrent signed
                    # N/M pair. Check all adverse signs, labelled as envelopes.
                    for signs in product((-1,1),repeat=3):
                        values=tuple(base[i]+signs[i]*factor*amplitude[i] for i in range(3))
                        cases.append((f'{combo.name}:component_envelope{signs}',*values,True))
                else:
                    values=tuple(sum(f*analysis_result.compound_forces_by_case[c][key][i]
                        for c,f in combo.factors.items()) for i in range(3))
                    cases.append((combo.name,*values,False))
            self.compound_demands.append(CompoundWallDesignDemand(section,tuple(cases),self.config.seismic.axial_compression_ratio_limit))
        return (combined_beams, combined_walls)

    def _combine_beam_demands(self, beam_forces_by_combo: dict[str, dict[tuple[int, int], tuple[float, float, float]]]) -> list[BeamDesignDemand]:
        demand_by_key: dict[tuple[int, int], BeamDesignDemand] = {}
        for unit in self.build_result.beam_element_units:
            key = (unit.beam_id, unit.story)
            pos_m = 0.0
            neg_m = 0.0
            shear = 0.0
            for combo_forces in beam_forces_by_combo.values():
                m_i, m_j, v = combo_forces[key]
                pos_m = max(pos_m, m_i, m_j, 0.0)
                neg_m = max(neg_m, -m_i, -m_j, 0.0)
                shear = max(shear, abs(v))
            metric = self.beam_checks[key]
            demand_by_key[key] = BeamDesignDemand(beam_id=unit.beam_id, story=unit.story, width_m=unit.width, depth_m=unit.depth, length_m=unit.length, positive_moment_n_m=pos_m, negative_moment_n_m=neg_m, shear_n=shear,
                moment_cases=tuple((*forces[key][:2],name in self.seismic_combos) for name,forces in beam_forces_by_combo.items()),
                shear_cases=tuple((v,limit,name in self.seismic_combos) for name,(v,limit) in metric.shear_checks.items()),coupling=metric.coupling)
        return list(demand_by_key.values())

    def _combine_wall_demands(self, wall_forces_by_combo: dict[str, dict[tuple[int, int], tuple[float, float, float]]]) -> list[WallDesignDemand]:
        demands: list[WallDesignDemand] = []
        story_profiles = {profile.story: profile for profile in self.config.resolve_story_profiles()}
        for unit in self.build_result.wall_story_element_units:
            key = (unit.wall_id, unit.story)
            axial = 0.0
            moment = 0.0
            shear = 0.0
            for combo_forces in wall_forces_by_combo.values():
                n, m, v = combo_forces[key]
                axial = max(axial, n)
                moment = max(moment, abs(m))
                shear = max(shear, abs(v))
            area_m2 = unit.member.length * unit.thickness
            concrete_grade = story_profiles[unit.story].material.concrete_grade.strip().upper()
            fc_pa = CONCRETE_COMPRESSIVE_STRENGTH_MPA[concrete_grade] * 1000000.0
            axial_ratio = axial / max(area_m2 * fc_pa, 1e-09)
            checks = self.wall_checks[key].shear_checks
            demands.append(WallDesignDemand(wall_id=unit.wall_id, story=unit.story, thickness_m=unit.thickness, length_m=unit.member.length, story_height_m=unit.story_height, axial_force_n=axial, moment_n_m=moment, shear_n=shear, axial_ratio=axial_ratio, is_bottom_reinforced_zone=unit.story <= 2,
                load_cases=tuple((forces[key][0],forces[key][1],checks[name][0],checks[name][1],name in self.seismic_combos)
                                 for name,forces in wall_forces_by_combo.items())))
        return demands
