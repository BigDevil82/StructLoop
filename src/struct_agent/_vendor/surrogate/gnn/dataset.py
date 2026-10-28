from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from torch_geometric.data import Data
from struct_agent._vendor.surrogate.features.consts import PARAM_FEATURES
CLASS_TASK = 'final_pass'
CAT_COLS = ['conc_bot', 'intensity', 'site_class', 'seismic_group']
FEATURE_COLS = PARAM_FEATURES
NUM_COLS = [col for col in FEATURE_COLS if col not in CAT_COLS]

class ParamPreprocessor:

    def __init__(self, num_cols: list[str], cat_cols: list[str]):
        self.num_cols = list(num_cols)
        self.cat_cols = list(cat_cols)
        self.num_mean: dict[str, float] = {}
        self.num_std: dict[str, float] = {}
        self.cat_vocab: dict[str, dict[str, int]] = {}

    def fit(self, df: pd.DataFrame) -> None:
        num = df[self.num_cols].copy()
        self.num_mean = {c: float(v) for c, v in num.mean(axis=0).items()}
        self.num_std = {c: float(v if float(v) != 0.0 else 1.0) for c, v in num.std(axis=0, ddof=0).items()}
        for col in self.cat_cols:
            raw = df[col].astype(str).fillna('<unk>')
            unique_vals = sorted((v for v in raw.unique() if v != '<unk>'))
            vocab = {'<unk>': 0}
            for i, val in enumerate(unique_vals, start=1):
                vocab[val] = i
            self.cat_vocab[col] = vocab

    def transform(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        x_num = df[self.num_cols].copy()
        mean = pd.Series(self.num_mean, dtype=float)
        std = pd.Series(self.num_std, dtype=float)
        x_num = x_num.fillna(mean)
        x_num = ((x_num - mean) / std).to_numpy(dtype=np.float32)
        cat_arrays: list[np.ndarray] = []
        for col in self.cat_cols:
            vocab = self.cat_vocab[col]
            raw = df[col].astype(str).fillna('<unk>')
            cat_arrays.append(raw.map(lambda v: vocab.get(v, 0)).to_numpy(dtype=np.int64))
        x_cat = np.stack(cat_arrays, axis=1)
        return (x_num, x_cat)

    def export(self) -> dict[str, object]:
        return {'num_cols': self.num_cols, 'cat_cols': self.cat_cols, 'num_mean': [self.num_mean[c] for c in self.num_cols], 'num_std': [self.num_std[c] for c in self.num_cols], 'cat_vocab': self.cat_vocab}

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> 'ParamPreprocessor':
        obj = cls(list(payload['num_cols']), list(payload['cat_cols']))
        obj.num_mean = {c: float(v) for c, v in zip(obj.num_cols, payload['num_mean'])}
        obj.num_std = {c: float(v) for c, v in zip(obj.num_cols, payload['num_std'])}
        obj.cat_vocab = {k: dict(v) for k, v in dict(payload['cat_vocab']).items()}
        return obj

class SurrogateGNNDataset(torch.utils.data.Dataset):

    def __init__(self, df: pd.DataFrame, graph_cache_dir: str | Path, preprocessor: ParamPreprocessor, target_col: str=CLASS_TASK):
        self.df = df.reset_index(drop=True)
        self.graph_cache_dir = Path(graph_cache_dir)
        self.preprocessor = preprocessor
        self.target_col = target_col
        self.x_num, self.x_cat = preprocessor.transform(self.df)
        if target_col in self.df.columns:
            self.y = self.df[target_col].astype(float).to_numpy(dtype=np.float32)
        else:
            self.y = np.zeros(len(self.df), dtype=np.float32)
        self._graph_cache: dict[str, dict[str, torch.Tensor]] = {}
        layout_ids = sorted(self.df['layout_id'].astype(str).unique().tolist())
        for layout_id in layout_ids:
            path = self.graph_cache_dir / f'{layout_id}.pt'
            if not path.exists():
                raise ValueError(f'Missing graph cache for layout {layout_id}: {path}')
            self._graph_cache[layout_id] = torch.load(path, map_location='cpu', weights_only=True)

    def __len__(self) -> int:
        return len(self.df)

    def __getitem__(self, idx: int) -> Data:
        row = self.df.iloc[idx]
        layout_id = str(row['layout_id'])
        g = self._graph_cache[layout_id]
        data = Data(x=g['x'], edge_index=g['edge_index'], edge_attr=g['edge_attr'], graph_feat=g['graph_feat'], p_num=torch.tensor(self.x_num[idx][None, :], dtype=torch.float32), p_cat=torch.tensor(self.x_cat[idx][None, :], dtype=torch.long), y=torch.tensor([self.y[idx]], dtype=torch.float32), sample_id=str(row.get('sample_id', '')), layout_id=layout_id)
        return data
