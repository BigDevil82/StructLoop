"""
训练和推理的配置参数
集中管理所有硬编码的常量和超参数
"""
from dataclasses import dataclass
from typing import List

@dataclass
class ModelConfig:
    """模型架构配置"""
    NODE_FEATURE_DIM: int = 25
    GEO_FEATURE_DIM: int = 9
    CONSTRAINT_DIM: int = 16
    EDGE_FEATURE_DIM: int = 8
    HIDDEN_DIM: int = 256
    OUTPUT_DIM: int = 32
    GAT_HEADS: int = 4
    NUM_CONV_LAYERS: int = 3
    DROPOUT: float = 0.2

@dataclass
class DataConfig:
    """数据处理配置"""
    DXF_DIR: str = 'data/dxf/shearwall_split_8_2'
    CACHE_DIR: str = 'data/cache/shearwall_dataset'
    SAVE_DIR: str = 'outputs/result/shearwall_pred/0126_cond_kfold'
    AUGMENTATIONS: List[str] = ('none', 'flip_x', 'flip_y', 'rot_90', 'rot_180', 'rot_270')
    ALIGNMENT_THRESHOLD: float = 200.0
    MIN_SHARED_LENGTH: float = 400.0
    INTERVAL_THRESHOLD: float = 0.1
    BUILDABLE_THRESHOLD: float = 0.4

@dataclass
class VisualizationConfig:
    """可视化配置"""
    PRED_PROB_THRESHOLD: float = 0.5
    PRED_RATIO_THRESHOLD: float = 0.1
    IOU_BUFFER_WIDTH: float = 0.5
    GT_WALL_COLOR: str = 'green'
    PRED_WALL_COLOR: str = 'red'
    BUILDABLE_COLOR: str = '#BBBBBB'
    DPI: int = 300
    FIG_SIZE_DOUBLE: tuple = (8, 6)
model_config = ModelConfig()
data_config = DataConfig()
viz_config = VisualizationConfig()
