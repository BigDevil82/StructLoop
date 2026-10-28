from time import time
from typing import Any
import openseespy.opensees as ops
from ..builders.base import AnalysisModelContext
from .combinations import cqc, srss
from .member_forces import extract_beam_force_tuple, extract_wall_force_tuple
from .modal import identify_dominant_modes, modal_periods_from_eigenvalues
from .results import DirectionResponse, ModalSummary, ResponseSpectrumCaseResult, StoryMetric

class ResponseSpectrumAnalyzer:

    def __init__(self, context: AnalysisModelContext):
        self.context = context
        self.xmin, self.xmax, self.ymin, self.ymax = context.bbox

    def _combine(self, modal_values: list[float], eigen_values: list[float]) -> float:
        if not modal_values:
            return 0.0
        num_modes = len(modal_values)
        damping = [self.context.config.seismic.damping_ratio] * num_modes
        scale_factors = [1.0] * num_modes
        if self.context.config.seismic.combination_method.upper() == 'CQC':
            return cqc(modal_values, eigen_values, damping, scale_factors)
        return srss(modal_values, scale_factors)

    def run(self) -> ResponseSpectrumCaseResult:
        eigen_values, modal_periods, modal_summary = self.run_modal_case()
        story_weights = self.compute_story_weights()
        direction_responses: dict[str, DirectionResponse] = {}
        beam_forces_by_dir: dict[str, dict[tuple[int, int], tuple[float, float, float]]] = {}
        wall_forces_by_dir: dict[str, dict[tuple[int, int], tuple[float, float, float]]] = {}
        for dir_idx, dir_name in ((1, 'X'), (2, 'Y')):
            response, beam_forces, wall_forces = self._run_rsa_analysis(dir_idx=dir_idx, dir_name=dir_name, eigen_values=eigen_values, story_weights=story_weights)
            direction_responses[dir_name] = response
            beam_forces_by_dir[dir_name] = beam_forces
            wall_forces_by_dir[dir_name] = wall_forces
        return ResponseSpectrumCaseResult(eigen_values=eigen_values, modal_periods=modal_periods, modal_summary=modal_summary, story_weights=story_weights, direction_responses=direction_responses, seismic_beam_forces_by_dir=beam_forces_by_dir, seismic_wall_forces_by_dir=wall_forces_by_dir)

    def extract_modal_summary(self, modal_periods: list[float], modal_props: dict[str, Any]) -> ModalSummary:
        self.context.logger.info('\n[校核器] 正在根据模态参与质量比识别主导模态...')
        translational_mode_index, torsional_mode_index = identify_dominant_modes(modal_props)
        translational_period = modal_periods[translational_mode_index - 1] if translational_mode_index is not None and translational_mode_index - 1 < len(modal_periods) else None
        torsional_period = modal_periods[torsional_mode_index - 1] if torsional_mode_index is not None and torsional_mode_index - 1 < len(modal_periods) else None
        period_ratio = None
        if translational_period and torsional_period:
            period_ratio = torsional_period / translational_period
        return ModalSummary(periods=modal_periods, translational_mode_index=translational_mode_index, translational_period=translational_period, torsional_mode_index=torsional_mode_index, torsional_period=torsional_period, period_ratio=period_ratio)

    def compute_story_weights(self) -> list[float]:
        story_weights = [0.0] * self.context.num_stories
        cumulative_mass = 0.0
        for story_index in reversed(range(self.context.num_stories)):
            cumulative_mass += self.context.floor_masses[story_index]
            story_weights[story_index] = cumulative_mass * self.context.config.seismic.gravity
        return story_weights

    def _compute_corner_displacements(self, dir_idx: int, center_disp: float, rotation_z: float, center_x: float, center_y: float) -> list[float]:
        dx = [self.xmin - center_x, self.xmax - center_x, self.xmax - center_x, self.xmin - center_x]
        dy = [self.ymin - center_y, self.ymin - center_y, self.ymax - center_y, self.ymax - center_y]
        if dir_idx == 1:
            return [center_disp - rotation_z * delta_y for delta_y in dy]
        return [center_disp + rotation_z * delta_x for delta_x in dx]

    def _analyze_mode(self, dir_idx: int, dir_name: str, mode_index: int, eigen_values: list[float], modal_drift_center: list[list[float]], modal_drift_corners: list[list[list[float]]], modal_story_shear: list[list[float]], beam_modal_forces: dict[tuple[int, int], dict[str, list[float]]], wall_modal_forces: dict[tuple[int, int], dict[str, list[float]]]) -> None:
        Tn = self.context.config.seismic.periods
        Sa = self.context.config.seismic.spectral_accel
        ops.responseSpectrumAnalysis(dir_idx, '-Tn', *Tn, '-Sa', *Sa, '-mode', mode_index)
        eigen_value = eigen_values[mode_index - 1]
        prev_center_disp = 0.0
        prev_corner_displacements = [0.0] * 4
        inertial_forces = [0.0] * self.context.num_stories
        for story_index, master in enumerate(self.context.master_nodes):
            center_disp = ops.nodeDisp(master, dir_idx)
            rotation_z = ops.nodeDisp(master, 6)
            center_x, center_y = (ops.nodeCoord(master, 1), ops.nodeCoord(master, 2))
            inertial_forces[story_index] = self.context.floor_masses[story_index] * eigen_value * center_disp
            corner_displacements = self._compute_corner_displacements(dir_idx, center_disp, rotation_z, center_x, center_y)
            story_height = self.context.story_heights[story_index]
            modal_drift_center[story_index].append((center_disp - prev_center_disp) / story_height)
            for corner_index, corner_disp in enumerate(corner_displacements):
                modal_drift_corners[corner_index][story_index].append((corner_disp - prev_corner_displacements[corner_index]) / story_height)
            prev_center_disp = center_disp
            prev_corner_displacements = corner_displacements
        cumulative_shear = 0.0
        for story_index in reversed(range(self.context.num_stories)):
            cumulative_shear += inertial_forces[story_index]
            modal_story_shear[story_index].append(cumulative_shear)
        for unit in self.context.beam_element_units:
            key = (unit.beam_id, unit.story)
            pos_m, neg_m, shear_v = extract_beam_force_tuple(unit.element_tag)
            store = beam_modal_forces.setdefault(key, {'pos': [], 'neg': [], 'shear': []})
            store['pos'].append(pos_m)
            store['neg'].append(neg_m)
            store['shear'].append(shear_v)
        for unit in self.context.wall_story_element_units:
            key = (unit.wall_id, unit.story)
            axial_n, moment_m, shear_v = extract_wall_force_tuple(unit)
            store = wall_modal_forces.setdefault(key, {'axial': [], 'moment': [], 'shear': []})
            store['axial'].append(axial_n)
            store['moment'].append(moment_m)
            store['shear'].append(shear_v)

    def _update_story_stiffness_ratios(self, metrics: list[StoryMetric], stiffness_values: list[float]) -> None:
        for story_index, metric in enumerate(metrics):
            current_stiffness = stiffness_values[story_index]
            next_stiffness = stiffness_values[story_index + 1] if story_index < len(metrics) - 1 else current_stiffness
            upper_stiffness = [stiffness_values[story_index + offset] for offset in range(1, 4) if story_index + offset < len(metrics)]
            average_upper_stiffness = sum(upper_stiffness) / len(upper_stiffness) if upper_stiffness else current_stiffness
            metric.stiffness_ratio_adjacent = current_stiffness / next_stiffness if next_stiffness > 1e-09 else 1.0
            metric.stiffness_ratio_average = current_stiffness / average_upper_stiffness if average_upper_stiffness > 1e-09 else 1.0

    def run_modal_case(self) -> tuple[list[float], list[float], ModalSummary]:
        ops.constraints('Transformation')
        ops.numberer('RCM')
        ops.system('UmfPack')
        ops.test('NormDispIncr', 1e-06, 20)
        ops.algorithm('Linear')
        ops.integrator('LoadControl', 0.0)
        ops.analysis('Static')
        num_modes_required = min(self.context.config.num_modes, self.context.num_stories * 2)
        self.context.logger.info(f'\n[校核器] 正在提取 {num_modes_required} 阶特征值 (UmfPack)...')
        start = time()
        eigen_values = ops.eigen('-genBandArpack', num_modes_required)
        end = time()
        self.context.logger.info(f'Eigenvalue extraction completed in {end - start:.2f} seconds.')
        if isinstance(eigen_values, (int, float)):
            eigen_values = [float(eigen_values)]
        else:
            eigen_values = [float(value) for value in eigen_values if float(value) > 1e-12]
        returned = ops.modalProperties('-return')
        if not isinstance(returned, dict):
            raise RuntimeError("modalProperties('-return') 未返回 dict，无法基于质量参与系数识别主导模态")
        modal_periods = modal_periods_from_eigenvalues(eigen_values)
        self.context.logger.info(f'Modal periods (s): {[round(period, 4) for period in modal_periods]}')
        return (eigen_values, modal_periods, self.extract_modal_summary(modal_periods, returned))

    def _run_rsa_analysis(self, dir_idx: int, dir_name: str, eigen_values: list[float], story_weights: list[float]) -> tuple[DirectionResponse, dict[tuple[int, int], tuple[float, float, float]], dict[tuple[int, int], tuple[float, float, float]]]:
        modal_drift_center = [[] for _ in range(self.context.num_stories)]
        modal_drift_corners = [[[] for _ in range(self.context.num_stories)] for _ in range(4)]
        modal_story_shear = [[] for _ in range(self.context.num_stories)]
        beam_modal_forces: dict[tuple[int, int], dict[str, list[float]]] = {}
        wall_modal_forces: dict[tuple[int, int], dict[str, list[float]]] = {}
        for mode_index, _ in enumerate(eigen_values, start=1):
            self._analyze_mode(dir_idx=dir_idx, dir_name=dir_name, mode_index=mode_index, eigen_values=eigen_values, modal_drift_center=modal_drift_center, modal_drift_corners=modal_drift_corners, modal_story_shear=modal_story_shear, beam_modal_forces=beam_modal_forces, wall_modal_forces=wall_modal_forces)
        metrics: list[StoryMetric] = []
        stiffness_values = [0.0] * self.context.num_stories
        for story_index in range(self.context.num_stories):
            story_shear = self._combine(modal_story_shear[story_index], eigen_values)
            center_drift = abs(self._combine(modal_drift_center[story_index], eigen_values))
            corner_drifts = [abs(self._combine(modal_drift_corners[corner_index][story_index], eigen_values)) for corner_index in range(4)]
            drift_max = max(corner_drifts)
            drift_min = min(corner_drifts)
            drift_avg = 0.5 * (drift_max + drift_min)
            torsion_ratio = drift_max / drift_avg if drift_avg > 1e-09 else 1.0
            shear_weight_ratio = story_shear / story_weights[story_index] if story_weights[story_index] > 1e-09 else 0.0
            stiffness = story_shear / center_drift if center_drift > 1e-09 else 0.0
            stiffness_values[story_index] = stiffness
            metrics.append(StoryMetric(story=story_index + 1, drift_max=drift_max, drift_avg=drift_avg, drift_center=center_drift, torsion_ratio=torsion_ratio, shear_weight_ratio=shear_weight_ratio, stiffness_k=stiffness, stiffness_ratio_adjacent=1.0, stiffness_ratio_average=1.0))
        self._update_story_stiffness_ratios(metrics, stiffness_values)
        response = DirectionResponse(direction=dir_name, metrics=metrics)
        return (response, self._combine_beam_modal_forces(beam_modal_forces, eigen_values), self._combine_wall_modal_forces(wall_modal_forces, eigen_values))

    def _combine_beam_modal_forces(self, beam_modal_forces: dict[tuple[int, int], dict[str, list[float]]], eigen_values: list[float]) -> dict[tuple[int, int], tuple[float, float, float]]:
        return {key: (self._combine(store['pos'], eigen_values), self._combine(store['neg'], eigen_values), self._combine(store['shear'], eigen_values)) for key, store in beam_modal_forces.items()}

    def _combine_wall_modal_forces(self, wall_modal_forces: dict[tuple[int, int], dict[str, list[float]]], eigen_values: list[float]) -> dict[tuple[int, int], tuple[float, float, float]]:
        return {key: (self._combine(store['axial'], eigen_values), self._combine(store['moment'], eigen_values), self._combine(store['shear'], eigen_values)) for key, store in wall_modal_forces.items()}
