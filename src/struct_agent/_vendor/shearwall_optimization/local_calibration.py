from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any
import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype
from sklearn.compose import ColumnTransformer
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, WhiteKernel
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from .core.contracts import EvaluationResult

@dataclass(frozen=True)
class OnlineLocalCalibrationConfig:
    enabled: bool = False
    min_samples: int = 25
    screening_target_recall: float = 0.995
    screening_threshold_scale: float = 0.1
    steel_min_samples: int = 25
    steel_gpr_min_samples: int = 50
    steel_lgbm_min_samples: int = 200
    max_gpr_train: int = 300

@dataclass(frozen=True)
class CalibratedFeasibility:
    probability: float
    threshold: float
    reject: bool
    model: str
    sample_count: int

class OnlineLocalCalibrator:

    def __init__(self, cfg: OnlineLocalCalibrationConfig):
        self.cfg = cfg
        self._records: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._dirty = True
        self._feas_model: LogisticRegression | None = None
        self._feas_threshold = 0.0
        self._steel_model: Pipeline | None = None
        self._steel_model_name = 'none'

    @property
    def sample_count(self) -> int:
        return len(self._records)

    def update(self, decision: dict[str, Any], result: EvaluationResult, *, global_probability: float | None, global_steel_kg: float | None) -> None:
        key = _decision_key(decision)
        steel_true = _finite_or_none(result.metrics.get('material_steel_kg'))
        self._records[key] = {'decision': dict(decision), 'feasible': bool(result.feasible), 'global_probability': None if global_probability is None else float(global_probability), 'global_steel_kg': None if global_steel_kg is None else float(global_steel_kg), 'steel_true_kg': steel_true}
        self._dirty = True

    def calibrate_feasibility(self, probability: float, fallback_threshold: float) -> CalibratedFeasibility:
        if not self.cfg.enabled:
            p = _clip_prob(probability)
            return CalibratedFeasibility(p, float(fallback_threshold), p < float(fallback_threshold), 'none', 0)
        self._fit_if_needed()
        p = _clip_prob(probability)
        if self._feas_model is None:
            threshold = float(fallback_threshold)
            model = 'global'
        else:
            p = float(self._feas_model.predict_proba(_logit_feature([p]))[0, 1])
            threshold = float(self._feas_threshold)
            model = 'platt'
        return CalibratedFeasibility(p, threshold, p < threshold, model, self.sample_count)

    def calibrate_steel(self, decision: dict[str, Any], steel_kg: float) -> tuple[float, str, int]:
        if not self.cfg.enabled:
            return (float(steel_kg), 'none', 0)
        self._fit_if_needed()
        if self._steel_model is None:
            return (float(steel_kg), 'global', self.sample_count)
        x = _steel_feature_frame([decision], [steel_kg])
        residual = float(self._steel_model.predict(x)[0])
        return (max(float(steel_kg) + residual, 0.0), self._steel_model_name, self.sample_count)

    def summary(self) -> dict[str, Any]:
        self._fit_if_needed()
        return {'local_calibration_enabled': bool(self.cfg.enabled), 'local_calibration_samples': int(self.sample_count), 'local_feasibility_model': 'platt' if self._feas_model is not None else 'global', 'local_feasibility_threshold': float(self._feas_threshold), 'local_steel_model': self._steel_model_name}

    def _fit_if_needed(self) -> None:
        if not self._dirty:
            return
        self._fit_feasibility()
        self._fit_steel()
        self._dirty = False

    def _fit_feasibility(self) -> None:
        rows = [r for r in self._records.values() if r['global_probability'] is not None]
        self._feas_model = None
        self._feas_threshold = 0.0
        if len(rows) < int(self.cfg.min_samples):
            return
        y = np.array([int(r['feasible']) for r in rows], dtype=int)
        if len(np.unique(y)) < 2:
            return
        p = np.array([float(r['global_probability']) for r in rows], dtype=np.float64)
        model = LogisticRegression(C=1.0, solver='lbfgs', random_state=0)
        model.fit(_logit_feature(p), y)
        calibrated = model.predict_proba(_logit_feature(p))[:, 1]
        pos = calibrated[y == 1]
        if len(pos) == 0:
            return
        miss_rate = max(0.0, min(1.0, 1.0 - float(self.cfg.screening_target_recall)))
        raw_threshold = float(np.quantile(pos, miss_rate))
        self._feas_model = model
        self._feas_threshold = max(0.0, min(1.0, raw_threshold * float(self.cfg.screening_threshold_scale)))

    def _fit_steel(self) -> None:
        rows = [r for r in self._records.values() if r['global_steel_kg'] is not None and r['steel_true_kg'] is not None]
        self._steel_model = None
        self._steel_model_name = 'none'
        if len(rows) < int(self.cfg.steel_min_samples):
            return
        self._steel_model_name, model = _build_steel_model(len(rows), self.cfg)
        if self._steel_model_name == 'gpr' and len(rows) > int(self.cfg.max_gpr_train):
            rows = rows[-int(self.cfg.max_gpr_train):]
        x = _steel_feature_frame([r['decision'] for r in rows], [float(r['global_steel_kg']) for r in rows])
        y = np.array([float(r['steel_true_kg']) - float(r['global_steel_kg']) for r in rows], dtype=np.float64)
        self._steel_model = Pipeline([('pre', _preprocessor(x, scaled=self._steel_model_name != 'lgbm')), ('model', model)])
        self._steel_model.fit(x, y)

def _build_steel_model(n: int, cfg: OnlineLocalCalibrationConfig) -> tuple[str, object]:
    if n >= int(cfg.steel_lgbm_min_samples):
        try:
            from lightgbm import LGBMRegressor
            return ('lgbm', LGBMRegressor(objective='regression', n_estimators=300, learning_rate=0.03, num_leaves=31, min_child_samples=10, subsample=0.9, colsample_bytree=0.9, reg_alpha=0.1, reg_lambda=1.0, random_state=0, verbose=-1))
        except ImportError:
            pass
    if n >= int(cfg.steel_gpr_min_samples):
        return ('gpr', GaussianProcessRegressor(kernel=RBF(length_scale=1.0) + WhiteKernel(noise_level=1.0), alpha=1e-06, normalize_y=True, random_state=0))
    return ('ridge', Ridge(alpha=10.0, random_state=0))

def _steel_feature_frame(decisions: list[dict[str, Any]], steel: list[float]) -> pd.DataFrame:
    rows = []
    for decision, steel_kg in zip(decisions, steel):
        row = dict(decision)
        row['global_steel_kg'] = float(steel_kg)
        row['log_global_steel_kg'] = math.log1p(max(float(steel_kg), 0.0))
        rows.append(row)
    return pd.DataFrame(rows)

def _preprocessor(x: pd.DataFrame, *, scaled: bool) -> ColumnTransformer:
    numeric = [c for c in x.columns if is_numeric_dtype(x[c])]
    categorical = [c for c in x.columns if not is_numeric_dtype(x[c])]
    num_steps = [('imputer', SimpleImputer(strategy='median'))]
    if scaled:
        num_steps.append(('scaler', StandardScaler()))
    return ColumnTransformer([('num', Pipeline(num_steps), numeric), ('cat', Pipeline([('imputer', SimpleImputer(strategy='most_frequent')), ('onehot', _onehot())]), categorical)], sparse_threshold=0.0)

def _onehot() -> OneHotEncoder:
    try:
        return OneHotEncoder(handle_unknown='ignore', sparse_output=False)
    except TypeError:
        return OneHotEncoder(handle_unknown='ignore', sparse=False)

def _logit_feature(p: Any) -> np.ndarray:
    p = np.array(p, dtype=np.float64)
    p = np.clip(p, 1e-06, 1.0 - 1e-06)
    return np.log(p / (1.0 - p)).reshape(-1, 1)

def _clip_prob(p: float) -> float:
    return float(max(1e-06, min(1.0 - 1e-06, float(p))))

def _finite_or_none(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None

def _decision_key(decision: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(((name, decision[name]) for name in sorted(decision.keys())))
