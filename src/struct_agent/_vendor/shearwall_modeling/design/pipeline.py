import logging
from ..analysis.results import AnalysisResult
from ..builders.base import ModelBuildResult
from ..core.config import ModelConfig
from ..core.constants import MIN_WALL_LEN_CHECK_THRESHOLD_M
from .beam import BeamReinforcementDesigner
from .constants import ReinforcementDesignConstants
from .extractor import DesignDemandExtractor
from .results import ReinforcementDesignSummary
from .wall import WallReinforcementDesigner

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
        wall_results = [self.wall_designer.design(demand, story_profiles[demand.story].material) for demand in wall_demands if demand.length_m > MIN_WALL_LEN_CHECK_THRESHOLD_M]
        return ReinforcementDesignSummary(beam_results=beam_results, wall_results=wall_results)
