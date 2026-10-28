import math
from typing import Any

def modal_periods_from_eigenvalues(eigen_values: list[float]) -> list[float]:
    return [2.0 * math.pi / math.sqrt(value) for value in eigen_values if value > 1e-12]

def safe_abs_float_list(values: Any, max_len: int) -> list[float]:
    if not isinstance(values, list):
        return [0.0] * max_len
    result: list[float] = []
    for value in values[:max_len]:
        try:
            result.append(abs(float(value)))
        except (TypeError, ValueError):
            result.append(0.0)
    if len(result) < max_len:
        result.extend([0.0] * (max_len - len(result)))
    return result

def identify_dominant_modes(modal_prop: dict[str, Any]) -> tuple[int | None, int | None]:
    """
    针对3D结构，根据模态质量参与比判别第一平动振型和第一扭转振型。

    参数
    ----------
    modal_prop : dict
        必须包含以下键：
        - "eigenLambda" 或 "eigenOmega" 等 (用于确定模态数量)
        - "partiMassRatiosMX" : List[float]  MX方向质量参与比 (%)
        - "partiMassRatiosMY" : List[float]  MY方向质量参与比 (%)
        - "partiMassRatiosRMZ": List[float]  绕Z轴扭转质量参与比 (%)

    返回
    -------
    tuple[Optional[int], Optional[int]]
        (第一平动模态编号, 第一扭转模态编号)，编号从1开始，未找到则为None
    """
    n_modes = len(modal_prop.get('eigenLambda', []))
    if n_modes == 0:
        raise ValueError('无法确定模态数量，缺少 eigenLambda/eigenOmega 等键')
    rat_mx = modal_prop['partiMassRatiosMX']
    rat_my = modal_prop['partiMassRatiosMY']
    rat_rmz = modal_prop['partiMassRatiosRMZ']
    first_trans = None
    first_tors = None
    for i in range(n_modes):
        trans_ratio = rat_mx[i] + rat_my[i]
        tors_ratio = rat_rmz[i]
        if tors_ratio > trans_ratio:
            if first_tors is None:
                first_tors = i + 1
        elif first_trans is None:
            first_trans = i + 1
        if first_trans is not None and first_tors is not None:
            break
    return (first_trans, first_tors)
