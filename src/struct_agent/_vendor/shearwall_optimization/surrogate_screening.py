from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import pandas as pd
from struct_agent._vendor.surrogate.features.consts import LAYOUT_FEATURES, PARAM_FEATURES

@dataclass(frozen=True)
class SurrogateScreeningConfig:
    enabled: bool = False
    artifact_path: str = 'data\\parametric\\ckpt\\baseline_gnn_room_hybrid_h256_screen995_v1\\gnn_final_pass.pt'
    graph_cache_dir: str = 'data\\parametric\\cache\\gnn_room_graph_cache'
    layout_features_path: str = 'data\\parametric\\surrogate_dataset\\layout_features.parquet'
    screening_threshold: float | None = None
    batch_size: int = 512
    num_workers: int = 0
    rejected_objective: float = 1000000000000.0

@dataclass(frozen=True)
class ScreeningDecision:
    reject: bool
    probability: float
    threshold: float

class GNNFeasibilityScreener:

    def __init__(self, cfg: SurrogateScreeningConfig, *, layout_id: str, fixed_params: dict[str, Any]):
        self.cfg = cfg
        self.layout_id = str(layout_id)
        self.fixed_params = dict(fixed_params)
        self._cache: dict[tuple[Any, ...], ScreeningDecision] = {}
        import torch
        from struct_agent._vendor.surrogate.gnn.dataset import ParamPreprocessor
        from struct_agent._vendor.surrogate.gnn.model import LayoutParamGNN
        self.torch = torch
        artifact = torch.load(Path(cfg.artifact_path), map_location='cpu', weights_only=True)
        self.threshold = float(artifact.get('screening_threshold', 0.0)) if cfg.screening_threshold is None else float(cfg.screening_threshold)
        self.pre = ParamPreprocessor.from_dict(artifact['preprocess'])
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

    def screen(self, decisions: list[dict[str, Any]]) -> list[ScreeningDecision]:
        out: list[ScreeningDecision | None] = [None] * len(decisions)
        pending: list[tuple[int, dict[str, Any], tuple[Any, ...]]] = []
        for i, decision in enumerate(decisions):
            key = _decision_key(decision)
            cached = self._cache.get(key)
            if cached is None:
                pending.append((i, decision, key))
            else:
                out[i] = cached
        if pending:
            df = self._build_frame([item[1] for item in pending])
            probs = self._predict_prob(df)
            for (idx, _, key), prob in zip(pending, probs):
                item = ScreeningDecision(reject=bool(float(prob) < self.threshold), probability=float(prob), threshold=self.threshold)
                self._cache[key] = item
                out[idx] = item
        return [item for item in out if item is not None]

    def _build_frame(self, decisions: list[dict[str, Any]]) -> pd.DataFrame:
        return self.build_frame(decisions)

    def build_frame(self, decisions: list[dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for i, decision in enumerate(decisions):
            row = {'layout_id': self.layout_id, 'sample_id': f'opt_{i}', **self.fixed_params, **decision, **self.layout_features}
            row.setdefault('conc_mid', row['conc_bot'])
            row.setdefault('conc_top', row['conc_bot'])
            rows.append(row)
        return pd.DataFrame(rows)

    def _predict_prob(self, df: pd.DataFrame) -> list[float]:
        from torch_geometric.loader import DataLoader
        from struct_agent._vendor.surrogate.gnn.dataset import SurrogateGNNDataset
        missing = [col for col in PARAM_FEATURES + LAYOUT_FEATURES if col not in df.columns]
        if missing:
            raise ValueError(f'Surrogate screening input missing columns: {missing}')
        ds = SurrogateGNNDataset(df, graph_cache_dir=self.cfg.graph_cache_dir, preprocessor=self.pre)
        loader = DataLoader(ds, batch_size=self.cfg.batch_size, shuffle=False, num_workers=self.cfg.num_workers)
        probs = []
        with self.torch.no_grad():
            for batch in loader:
                batch = batch.to(self.device)
                logits = self.model(batch)
                probs.extend(self.torch.sigmoid(logits).detach().cpu().tolist())
        return [float(v) for v in probs]

def _decision_key(decision: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(((name, decision[name]) for name in sorted(decision.keys())))
