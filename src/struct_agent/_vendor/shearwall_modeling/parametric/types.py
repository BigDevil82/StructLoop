from dataclasses import dataclass
from typing import Any, Literal
SamplingMethod = Literal['random', 'lhs']
StorageFormat = Literal['parquet', 'hdf5']
BuilderName = Literal['detailed_shell', 'equivalent_frame', 'mvlem_frame']

@dataclass(frozen=True)
class ParametricModelParams:
    N: int
    tw_bot: int
    tw_mid: int
    tw_top: int
    hb_main: int
    bb_main: int
    hb_sec: int
    bb_sec: int
    hs: int
    conc_bot: str
    conc_mid: str
    conc_top: str
    intensity: float
    site_class: str
    seismic_group: int
    h_story: float = 2.9

@dataclass(frozen=True)
class DatasetGenerationConfig:
    layout_dir: str = 'data\\dxf\\cad_json_data\\fem_raw'
    output_dir: str = 'outputs\\result\\parametric_dataset'
    samples_per_layout: int = 500
    samples_per_task: int = 20
    progress_log_interval: int = 200
    sampling_method: SamplingMethod = 'lhs'
    storage_format: StorageFormat = 'parquet'
    builder_name: BuilderName = 'mvlem_frame'
    num_modes: int = 6
    max_workers: int | None = None
    seed: int = 42
    overwrite: bool = False
    input_unit_scale_to_m: float = 0.001
    enable_auto_scale: bool = True
    scale_low: float = 2.0
    scale_high: float = 6.0
    scale_seed: int = 42
    manual_scale_factor: float | None = None

@dataclass(frozen=True)
class LayoutGenerationTask:
    layout_path: str
    output_dir: str
    cfg: DatasetGenerationConfig

@dataclass(frozen=True)
class SampleChunkTask:
    layout_path: str
    layout_id: str
    cfg: DatasetGenerationConfig
    sample_start_idx: int
    params_chunk: list[ParametricModelParams]

@dataclass(frozen=True)
class SampleChunkResult:
    layout_id: str
    rows: list[dict[str, Any]]

@dataclass(frozen=True)
class LayoutDatasetSummary:
    layout_id: str
    output_path: str
    total_samples: int
    converged_samples: int
    feasible_samples: int
    skipped: bool = False
    error: str | None = None

@dataclass(frozen=True)
class ParametricAnalysisResult:
    converged: bool
    feasible: bool
    design_passed: bool
    design_failed_beam_count: int
    design_failed_wall_count: int
    material_concrete_kg: float
    material_steel_kg: float
    mass_total_t: float
    T1: float
    T2: float
    T3: float
    T4: float
    T5: float
    T6: float
    period_ratio: float
    torsion_ratio: float
    min_shear_weight_ratio: float
    max_drift_ratio: float
    min_stiffness_ratio: float
    max_wall_axial_ratio: float
    max_wall_axial_limit: float
    max_wall_shear_ratio: float
    max_wall_shear_limit: float
    max_beam_shear_ratio: float
    max_beam_shear_limit: float
    period_ratio_available: bool = True
    torsion_passed: bool = True
    shear_weight_passed: bool = True
    stiffness_passed: bool = True
    drift_passed: bool = True
    period_ratio_passed: bool = True
    wall_axial_passed: bool = True
    wall_shear_passed: bool = True
    beam_shear_passed: bool = True
    error: str = ''
