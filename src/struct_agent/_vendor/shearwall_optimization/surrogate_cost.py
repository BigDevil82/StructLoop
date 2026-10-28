from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import pandas as pd
from struct_agent._vendor.surrogate.features.consts import LAYOUT_FEATURES
from .cost_estimation import CostBreakdown, estimate_concrete_kg, material_cost

@dataclass(frozen=True)
class SurrogateCostPreselectionConfig:
    enabled: bool = False
    steel_artifact_path: str = 'data\\parametric\\ckpt\\steel_gnn_room_lr5e4_b512\\gnn_steel.pt'
    graph_cache_dir: str = 'data\\parametric\\cache\\gnn_room_graph_cache'
    layout_features_path: str = 'data\\parametric\\surrogate_dataset\\layout_features.parquet'
    eval_ratio: float = 0.4
    pre_feasible_eval_ratio: float = 0.8
    min_eval_count: int = 8
    batch_size: int = 512
    num_workers: int = 0
    skipped_objective: float = 1000000000000.0
    feasibility_penalty_cost: float = 1000000.0
    feasibility_hinge_target: float = 0.5
    cost_quota_ratio: float = 0.6
    feasibility_quota_ratio: float = 0.25
    exploration_quota_ratio: float = 0.15

@dataclass(frozen=True)
class SurrogateCostPrediction:
    score: float
    steel_kg: float
    concrete_kg: float
    concrete_cost: float
    steel_cost: float
    material_cost: float
    feasible_probability: float | None = None
    infeasible_risk: float = 0.0

class GNNMaterialCostEstimator:

    def __init__(self, cfg: SurrogateCostPreselectionConfig, *, layout_id: str, fixed_params: dict[str, Any], steel_price_per_kg: float):
        self.cfg = cfg
        self.layout_id = str(layout_id)
        self.fixed_params = dict(fixed_params)
        self.steel_price_per_kg = float(steel_price_per_kg)
        self._steel_cache: dict[tuple[Any, ...], float] = {}
        self._cost_cache: dict[tuple[Any, ...], SurrogateCostPrediction] = {}
        import torch
        from struct_agent._vendor.surrogate.gnn.dataset import ParamPreprocessor
        from struct_agent._vendor.surrogate.gnn.model import LayoutParamGNN
        self.torch = torch
        artifact = torch.load(Path(cfg.steel_artifact_path), map_location='cpu', weights_only=True)
        self.pre = ParamPreprocessor.from_dict(artifact['preprocess'])
        self.y_mean = float(artifact['target_log_mean'])
        self.y_std = float(artifact['target_log_std'])
        self.model = LayoutParamGNN(**artifact['model_cfg'])
        self.model.load_state_dict(artifact['state_dict'])
        self.model.eval()
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model = self.model.to(self.device)
        feature_df = pd.read_parquet(cfg.layout_features_path)
        match = feature_df[feature_df['layout_id'].astype(str) == self.layout_id]
        if match.empty:
            raise ValueError(f'Missing layout features for layout_id={self.layout_id}: {cfg.layout_features_path}')
        self.layout_features = match.iloc[0][LAYOUT_FEATURES].to_dict()

    def predict(self, decisions: list[dict[str, Any]], *, feasible_probabilities: list[float | None] | None=None) -> list[SurrogateCostPrediction]:
        probs = feasible_probabilities or [None] * len(decisions)
        out: list[SurrogateCostPrediction | None] = [None] * len(decisions)
        pending: list[tuple[int, dict[str, Any], float | None, tuple[Any, ...]]] = []
        for i, (decision, prob) in enumerate(zip(decisions, probs)):
            key = _decision_key(decision)
            cached = self._cost_cache.get((*key, ('prob', prob)))
            if cached is None:
                pending.append((i, decision, prob, key))
            else:
                out[i] = cached
        if pending:
            items = [item[1] for item in pending]
            steel = self._predict_steel(items)
            frames = self._build_frame(items).to_dict('records')
            for (idx, _, prob, key), steel_kg, row in zip(pending, steel, frames):
                cost = material_cost(concrete_kg=estimate_concrete_kg(row), steel_kg=steel_kg, row=row, steel_price_per_kg=self.steel_price_per_kg)
                pred = self._prediction_from_cost(cost, prob)
                self._cost_cache[*key, ('prob', prob)] = pred
                out[idx] = pred
        return [item for item in out if item is not None]

    def _prediction_from_cost(self, cost: CostBreakdown, prob: float | None) -> SurrogateCostPrediction:
        risk = 0.0 if prob is None else max(0.0, float(self.cfg.feasibility_hinge_target) - float(prob))
        score = float(cost.material_cost) + float(self.cfg.feasibility_penalty_cost) * risk
        return SurrogateCostPrediction(score=score, steel_kg=cost.steel_kg, concrete_kg=cost.concrete_kg, concrete_cost=cost.concrete_cost, steel_cost=cost.steel_cost, material_cost=cost.material_cost, feasible_probability=None if prob is None else float(prob), infeasible_risk=risk)

    def _predict_steel(self, decisions: list[dict[str, Any]]) -> list[float]:
        out: list[float | None] = [None] * len(decisions)
        pending: list[tuple[int, dict[str, Any], tuple[Any, ...]]] = []
        for i, decision in enumerate(decisions):
            key = _decision_key(decision)
            cached = self._steel_cache.get(key)
            if cached is None:
                pending.append((i, decision, key))
            else:
                out[i] = cached
        if pending:
            df = self._build_frame([item[1] for item in pending])
            preds = self._predict_df(df)
            for (idx, _, key), pred in zip(pending, preds):
                self._steel_cache[key] = float(pred)
                out[idx] = float(pred)
        return [float(v) for v in out if v is not None]

    def _build_frame(self, decisions: list[dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for i, decision in enumerate(decisions):
            row = {'layout_id': self.layout_id, 'sample_id': f'opt_cost_{i}', **self.fixed_params, **decision, **self.layout_features}
            row.setdefault('conc_mid', row['conc_bot'])
            row.setdefault('conc_top', row['conc_bot'])
            rows.append(row)
        return pd.DataFrame(rows)

    def _predict_df(self, df: pd.DataFrame) -> list[float]:
        from torch_geometric.loader import DataLoader
        from struct_agent._vendor.surrogate.gnn.dataset import SurrogateGNNDataset
        ds = SurrogateGNNDataset(df, graph_cache_dir=self.cfg.graph_cache_dir, preprocessor=self.pre)
        loader = DataLoader(ds, batch_size=self.cfg.batch_size, shuffle=False, num_workers=self.cfg.num_workers)
        preds = []
        with self.torch.no_grad():
            for batch in loader:
                batch = batch.to(self.device)
                pred_norm = self.model(batch)
                pred = self.torch.expm1(pred_norm * self.y_std + self.y_mean)
                preds.extend(pred.detach().cpu().tolist())
        return [float(max(v, 0.0)) for v in preds]

def _decision_key(decision: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(((name, decision[name]) for name in sorted(decision.keys())))
