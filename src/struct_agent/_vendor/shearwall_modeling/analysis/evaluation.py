import logging
from ..builders.base import AnalysisModelContext
from ..core.config import ModelConfig
from ..core.constants import MIN_SHEAR_WEIGHT_RATIO_BY_INTENSITY
from .basic_static_case import LinearSuperpositionAnalyzer
from .checkers import BeamShearPressureChecker, DirectionChecker, InterstoryDriftChecker, PeriodRatioChecker, ShearWeightRatioChecker, StiffnessChecker, TorsionChecker, WallULSChecker
from .response_spectrum import ResponseSpectrumAnalyzer
from .results import AnalysisResult, DirectionCheckResult, DirectionResponse, OverallCheckResult, ResponseSpectrumCaseResult, init_direction_check_result
from .uls_combinations import ULSCombinationAnalyzer

class AnalysisResultBuilder:

    def __init__(self, context: AnalysisModelContext):
        self.context = context
        self.rsa_analyzer = ResponseSpectrumAnalyzer(context)
        self.basic_case_analyzer = LinearSuperpositionAnalyzer(context)
        self.uls_analyzer = ULSCombinationAnalyzer(context)

    def build(self) -> AnalysisResult:
        rsa_result = self.rsa_analyzer.run()
        basic_case_result = self.basic_case_analyzer.run_basic_cases(rsa_result=rsa_result)
        beam_case_forces = {case_name: case_result.get('beam_forces', {}) for case_name, case_result in basic_case_result.items()}
        wall_case_forces = {case_name: case_result.get('wall_forces', {}) for case_name, case_result in basic_case_result.items()}
        uls_result = self.uls_analyzer.run(beam_case_forces=beam_case_forces, wall_case_forces=wall_case_forces)
        return self._compose_snapshot(rsa_result, uls_result.beam_forces_by_combo, uls_result.wall_forces_by_combo, uls_result.wall_metrics, uls_result.beam_metrics)

    def _compose_snapshot(self, rsa_result: ResponseSpectrumCaseResult, beam_forces_by_combo, wall_forces_by_combo, wall_uls_metrics, beam_uls_metrics) -> AnalysisResult:
        return AnalysisResult(eigen_values=rsa_result.eigen_values, modal_periods=rsa_result.modal_periods, modal_summary=rsa_result.modal_summary, story_weights=rsa_result.story_weights, direction_responses=rsa_result.direction_responses, beam_forces_by_combo=beam_forces_by_combo, wall_forces_by_combo=wall_forces_by_combo, wall_uls_metrics=wall_uls_metrics, beam_uls_metrics=beam_uls_metrics)

class SeismicEvaluationPipeline:
    """Coordinate modal response extraction and code checks."""

    def __init__(self, config: ModelConfig):
        shear_weight_checker = ShearWeightRatioChecker.from_intensity(config.seismic.intensity)
        self.direction_checkers: list[DirectionChecker] = [TorsionChecker(), shear_weight_checker, StiffnessChecker(), InterstoryDriftChecker()]
        self.period_ratio_checker = PeriodRatioChecker()
        self.wall_uls_checker = WallULSChecker()
        self.beam_shear_checker = BeamShearPressureChecker()

    def _evaluate_direction(self, response: DirectionResponse) -> DirectionCheckResult:
        result = init_direction_check_result(response)
        for checker in self.direction_checkers:
            checker.apply(response, result)
        return result

    def evaluate(self, anysis_result: AnalysisResult) -> tuple[OverallCheckResult, dict[str, DirectionCheckResult]]:
        overall_result = OverallCheckResult()
        dir_chk_results: dict[str, DirectionCheckResult] = {}
        for dir_name in ('X', 'Y'):
            response = anysis_result.direction_responses[dir_name]
            dir_chk_results[dir_name] = self._evaluate_direction(response)
        overall_result.is_torsion_passed = all((result.is_torsion_passed for result in dir_chk_results.values()))
        overall_result.is_shear_weight_passed = all((result.is_shear_weight_passed for result in dir_chk_results.values()))
        overall_result.is_stiffness_passed = all((result.is_stiffness_passed for result in dir_chk_results.values()))
        overall_result.is_interstory_drift_passed = all((result.is_interstory_drift_passed for result in dir_chk_results.values()))
        self.period_ratio_checker.apply(anysis_result.modal_summary, overall_result)
        self.wall_uls_checker.apply(anysis_result.wall_uls_metrics, overall_result)
        self.beam_shear_checker.apply(anysis_result.beam_uls_metrics, overall_result)
        return (overall_result, dir_chk_results)

class EvaluationReportPrinter:

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def print(self, config: ModelConfig, analysis_result: AnalysisResult, overall_result: OverallCheckResult, dir_results: dict[str, DirectionCheckResult]) -> None:
        self.logger.info('\n' + '=' * 20 + '结构抗震规范核心指标综合校核报告' + '=' * 20)
        modal_summary = analysis_result.modal_summary
        wall_uls_metrics = analysis_result.wall_uls_metrics
        beam_uls_metrics = analysis_result.beam_uls_metrics
        self.min_shear_ratio = MIN_SHEAR_WEIGHT_RATIO_BY_INTENSITY[config.seismic.intensity]
        if modal_summary is not None:
            self.logger.info('【模态结果】')
            self.logger.info(' 前n阶周期:')
            for idx, period in enumerate(modal_summary.periods, start=1):
                self.logger.info(f'  第{idx}阶: {period:.4f} s')
            if modal_summary.period_ratio is not None:
                self.logger.info(f' 首个平动周期/首个扭转周期: 第{modal_summary.translational_mode_index}阶 {modal_summary.translational_period:.4f} s / 第{modal_summary.torsional_mode_index}阶 {modal_summary.torsional_period:.4f} s')
                self.logger.info(f" 周期比 T_torsion / T_translation < 0.9: {modal_summary.period_ratio:.3f} ({('✅通过' if overall_result.is_period_ratio_passed else '❌超限')})")
            else:
                self.logger.info(' 首个平动或扭转主导模态未识别，周期比无法校核。')
        for dir_name, result in dir_results.items():
            self.logger.info(f'【{dir_name}向校核结果】')
            self.logger.info(f" -> 扭转不规则 (限值 1.2/1.5): {('✅通过' if result.is_torsion_passed else '❌超限')}")
            self.logger.info(f" -> 最小剪重比 (限值 {self.min_shear_ratio}): {('✅通过' if result.is_shear_weight_passed else '❌超限')}")
            self.logger.info(f" -> 刚度突变 (限值 0.7/0.8): {('✅通过' if result.is_stiffness_passed else '❌超限')}")
            self.logger.info(f" -> 最大层间位移角 (限值 1/{int(round(1.0 / result.interstory_drift_limit))}): {result.max_interstory_drift_ratio:.6f} (控制层: {result.max_interstory_drift_story}层) {('✅通过' if result.is_interstory_drift_passed else '❌超限')}")
            self.logger.info('楼层 | 层间位移角Max | 位移比(Max/Avg) | 剪重比(%) | 刚度比γ1 | 刚度比γ2')
            self.logger.info('-' * 60)
            for metric in reversed(result.metrics):
                self.logger.info(f'  {metric.story:02d} | {metric.drift_max:.6f} | {metric.torsion_ratio:.3f} | {metric.shear_weight_ratio * 100:.2f} | {metric.gamma1:.2f} | {metric.gamma2:.2f}')
        if wall_uls_metrics:
            self.logger.info('【墙肢轴压比校核】')
            worst = max(wall_uls_metrics, key=lambda item: item.axial_ratio)
            self.logger.info(f" 控制墙肢: #{worst.wall_id}, 轴压比={worst.axial_ratio:.3f}, 限值={worst.axial_ratio_limit:.3f}, {('✅通过' if worst.is_axial_passed else '❌超限')}")
            self.logger.info('【剪压比校核】')
            wall_worst = max(wall_uls_metrics, key=lambda item: item.shear_pressure_ratio)
            self.logger.info(f" 墙控制构件: #{wall_worst.wall_id}-S{wall_worst.story}, 剪压比={wall_worst.shear_pressure_ratio:.3f}, 限值={wall_worst.shear_pressure_ratio_limit:.3f}, 组合={wall_worst.shear_control_combo}, {('✅通过' if wall_worst.is_shear_pressure_passed else '❌超限')}, length={wall_worst.length:.2f}m, thickness={wall_worst.thickness:.2f}m")
        if beam_uls_metrics:
            beam_worst = max(beam_uls_metrics, key=lambda item: item.shear_pressure_ratio)
            self.logger.info(f" 连梁控制构件: #{beam_worst.beam_id}-S{beam_worst.story}, 剪压比={beam_worst.shear_pressure_ratio:.3f}, 限值={beam_worst.shear_pressure_ratio_limit:.3f}, 组合={beam_worst.shear_control_combo}, {('✅通过' if beam_worst.is_shear_pressure_passed else '❌超限')}, length={beam_worst.length:.2f}m")
