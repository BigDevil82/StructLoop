import logging
from dataclasses import replace
from shapely.geometry import LineString, GeometryCollection
from ..analysis.results import AnalysisResult
from ..builders.base import ModelBuildResult
from ..core.config import ModelConfig
from .beam import BeamReinforcementDesigner
from .constants import ReinforcementDesignConstants
from .extractor import DesignDemandExtractor
from .results import ReinforcementDesignSummary, MaterialUsage
from .wall import WallReinforcementDesigner, design_compound_section

class ReinforcementDesignPipeline:

    def __init__(self, build_result: ModelBuildResult, analysis_result: AnalysisResult, config: ModelConfig, logger: logging.Logger, constants: ReinforcementDesignConstants | None=None):
        self.build_result = build_result
        self.analysis_result = analysis_result
        self.config = config
        self.logger = logger
        self.constants = constants or ReinforcementDesignConstants()
        self.extractor = DesignDemandExtractor(build_result, config, logger)
        self.beam_designer = BeamReinforcementDesigner(self.constants)
        self.wall_designer = WallReinforcementDesigner(self.constants)

    def run(self) -> ReinforcementDesignSummary:
        beam_demands, wall_demands = self.extractor.extract(self.analysis_result)
        story_profiles = {profile.story: profile for profile in self.config.resolve_story_profiles()}
        beam_results = [self.beam_designer.design(demand, story_profiles[demand.story].material) for demand in beam_demands]
        wall_results = [self.wall_designer.design(demand, story_profiles[demand.story].material) for demand in wall_demands]
        by_key={(r.wall_id,r.story):r for r in wall_results}
        shear_checks={(m.wall_id,m.story):m.is_shear_pressure_passed for m in self.analysis_result.wall_uls_metrics}
        compound_results=[]
        fiber_cache={}  # Geometry only; discarded after this evaluation, never shared across layouts.
        for demand in self.extractor.compound_demands:
            section=demand.section
            result=design_compound_section(demand,story_profiles[section.story].material,self.constants,fiber_cache=fiber_cache)
            compound_results.append(result)
            horizontal_ratio=max(by_key[u.wall_id,u.story].horizontal_distributed_steel_mm2_per_m/(u.thickness*1e6)
                                 for u in section.units)
            height=section.units[0].story_height
            volume_ratio=.006 if result.axial_ratio>(.3 if section.story<=2 else .4) else .004
            steel_kg=(result.longitudinal_steel_mm2*1e-6*height+horizontal_ratio*result.area_m2*height
                +volume_ratio*result.boundary_area_m2*height)*self.constants.steel_density_kg_m3
            concrete_kg=result.area_m2*height*self.constants.concrete_density_kg_m3
            occupied=GeometryCollection()
            for u in sorted(section.units,key=lambda u:(-u.member.length,u.wall_id)):
                rectangle=LineString([(u.member.start.x,u.member.start.y),(u.member.end.x,u.member.end.y)]).buffer(u.thickness/2,cap_style=2)
                share=rectangle.difference(occupied).area/result.area_m2
                occupied=occupied.union(rectangle)
                row=by_key[u.wall_id,u.story]
                messages=[f'shared_{section.kind}_section_{section.section_id}',*result.messages]
                if not shear_checks[u.wall_id,u.story]:messages.append('wall_shear_section_insufficient')
                # Per-end rectangular boundary areas no longer describe this
                # member; the shared area and checks live in compound_results.
                by_key[u.wall_id,u.story]=replace(row,boundary_longitudinal_steel_mm2=0.,boundary_stirrup_area_mm2=0.,
                    material_usage=MaterialUsage(concrete_kg*share,steel_kg*share),
                    is_section_insufficient=not result.is_passed or not shear_checks[u.wall_id,u.story],
                    messages=messages,compound_section_id=section.section_id,shared_wall_ids=section.wall_ids)
        return ReinforcementDesignSummary(beam_results=beam_results,
            wall_results=[by_key[r.wall_id,r.story] for r in wall_results],compound_results=compound_results)
