import openseespy.opensees as ops
from ..builders.base import AnalysisModelContext
from .member_forces import extract_beam_force_tuple, extract_wall_force_tuple
from .results import ResponseSpectrumCaseResult

class LinearSuperpositionAnalyzer:

    def __init__(self, context: AnalysisModelContext, wind_basic_pressure_kpa: float=0.5, wind_shape_coeff: float=1.3, wind_vibration_coeff: float=1.0, wind_importance_coeff: float=1.0, wind_height_exponent: float=0.16, wind_ref_height_m: float=10.0, wind_min_height_coeff: float=1.0):
        self.context = context
        self.basic_cases = ['Dead', 'Live', 'WindX', 'WindY']
        self.wind_basic_pressure_kpa = max(float(wind_basic_pressure_kpa), 0.0)
        self.wind_shape_coeff = max(float(wind_shape_coeff), 0.0)
        self.wind_vibration_coeff = max(float(wind_vibration_coeff), 0.0)
        self.wind_importance_coeff = max(float(wind_importance_coeff), 0.0)
        self.wind_height_exponent = max(float(wind_height_exponent), 0.0)
        self.wind_ref_height_m = max(float(wind_ref_height_m), 1.0)
        self.wind_min_height_coeff = max(float(wind_min_height_coeff), 0.1)

    def _configure_static_analysis(self) -> None:
        """配置线性静力分析（通用配置）"""
        ops.wipeAnalysis()
        ops.constraints('Transformation')
        ops.numberer('RCM')
        ops.system('UmfPack')
        ops.test('NormDispIncr', 1e-06, 20)
        ops.algorithm('Linear')
        ops.integrator('LoadControl', 1.0)
        ops.analysis('Static')

    def _apply_story_vertical_loads(self, story_forces_n: list[float]) -> None:
        for story_index, floor_nodes in enumerate(self.context.floor_story_nodes):
            if not floor_nodes:
                continue
            nodal_force = story_forces_n[story_index] / len(floor_nodes)
            for node in floor_nodes:
                ops.load(node, 0.0, 0.0, -nodal_force, 0.0, 0.0, 0.0)

    def _story_dead_force_n(self, story_index: int) -> float:
        profile = self.context.story_profiles[story_index]
        dead_surface_force_n = self.context.floor_area * profile.mass_source.dead_kpa * 1000.0
        self_weight_force_n = self.context.floor_self_masses[story_index] * profile.mass_source.gravity
        return dead_surface_force_n + self_weight_force_n

    def _story_live_force_n(self, story_index: int) -> float:
        profile = self.context.story_profiles[story_index]
        return self.context.floor_area * profile.mass_source.live_kpa * 1000.0

    def _wind_height_coeff(self, z_m: float) -> float:
        ratio = max(float(z_m), 0.0) / self.wind_ref_height_m
        value = ratio ** self.wind_height_exponent
        return max(value, self.wind_min_height_coeff)

    def _wind_story_forces_by_code(self, direction: str) -> list[float]:
        xmin, xmax, ymin, ymax = self.context.bbox
        width_m = max(ymax - ymin, 1e-09) if direction == 'X' else max(xmax - xmin, 1e-09)
        base_pressure_pa = self.wind_basic_pressure_kpa * 1000.0
        story_forces: list[float] = []
        for profile in self.context.story_profiles:
            z_mid = 0.5 * (profile.z_bottom + profile.z_top)
            mu_z = self._wind_height_coeff(z_mid)
            pressure_pa = base_pressure_pa * self.wind_importance_coeff * self.wind_vibration_coeff * self.wind_shape_coeff * mu_z
            facade_area_m2 = width_m * profile.story_height
            story_forces.append(pressure_pa * facade_area_m2)
        return story_forces

    def _apply_lateral_load(self, story_forces_n: list[float], direction: str) -> None:
        for story_index, node in enumerate(self.context.master_nodes):
            force = story_forces_n[story_index]
            if direction == 'X':
                ops.load(node, force, 0.0, 0.0, 0.0, 0.0, 0.0)
            elif direction == 'Y':
                ops.load(node, 0.0, force, 0.0, 0.0, 0.0, 0.0)
            else:
                raise ValueError(f'Unsupported direction {direction}.')

    def _apply_dead_load(self) -> None:
        story_forces_n = [self._story_dead_force_n(idx) for idx in range(self.context.num_stories)]
        self._apply_story_vertical_loads(story_forces_n)

    def _apply_live_load(self) -> None:
        story_forces_n = [self._story_live_force_n(idx) for idx in range(self.context.num_stories)]
        self._apply_story_vertical_loads(story_forces_n)

    def _apply_wind_x_load(self) -> None:
        story_forces_n = self._wind_story_forces_by_code(direction='X')
        self._apply_lateral_load(story_forces_n, direction='X')

    def _apply_wind_y_load(self) -> None:
        story_forces_n = self._wind_story_forces_by_code(direction='Y')
        self._apply_lateral_load(story_forces_n, direction='Y')

    def _extract_case_forces(self) -> tuple[dict[tuple[int, int], tuple[float, float, float]], dict[tuple[int, int], tuple[float, float, float]]]:
        beam_forces = {(unit.beam_id, unit.story): extract_beam_force_tuple(unit.element_tag) for unit in self.context.beam_element_units}
        wall_forces = {(unit.wall_id, unit.story): extract_wall_force_tuple(unit) for unit in self.context.wall_story_element_units}
        return (beam_forces, wall_forces)

    def _run_static_basic_case(self, case_name: str) -> tuple[dict[tuple[int, int], tuple[float, float, float]], dict[tuple[int, int], tuple[float, float, float]]]:
        ts_tag = 71000 + self.basic_cases.index(case_name) + 1
        pat_tag = 71000 + self.basic_cases.index(case_name) + 1
        ops.reset()
        ops.timeSeries('Linear', ts_tag)
        ops.pattern('Plain', pat_tag, ts_tag)
        if case_name == 'Dead':
            self._apply_dead_load()
        elif case_name == 'Live':
            self._apply_live_load()
        elif case_name == 'WindX':
            self._apply_wind_x_load()
        elif case_name == 'WindY':
            self._apply_wind_y_load()
        else:
            raise ValueError(f'Unsupported basic case {case_name}.')
        self._configure_static_analysis()
        if ops.analyze(1) != 0:
            raise RuntimeError(f'Static analysis failed for basic case: {case_name}')
        ops.reactions()
        beam_forces, wall_forces = self._extract_case_forces()
        ops.remove('loadPattern', pat_tag)
        ops.reset()
        return (beam_forces, wall_forces)

    def run_basic_cases(self, rsa_result: ResponseSpectrumCaseResult | None=None) -> dict:
        """Run basic static cases and append EqX/EqY from RSA directional results."""
        basic_results: dict[str, dict] = {}
        for case in self.basic_cases:
            beam_forces, wall_forces = self._run_static_basic_case(case)
            basic_results[case] = {'beam_forces': beam_forces, 'wall_forces': wall_forces}
        if rsa_result is None:
            raise RuntimeError('rsa_result is required for EqX/EqY basic cases.')
        basic_results['EqX'] = {'beam_forces': rsa_result.seismic_beam_forces_by_dir['X'], 'wall_forces': rsa_result.seismic_wall_forces_by_dir['X']}
        basic_results['EqY'] = {'beam_forces': rsa_result.seismic_beam_forces_by_dir['Y'], 'wall_forces': rsa_result.seismic_wall_forces_by_dir['Y']}
        return basic_results

