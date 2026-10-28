"""Copy only default inference weights and one reference case; never overwrite."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from struct_agent.adapters.geometry import read_legacy_layout
from struct_agent.io.artifacts import sha256, write_json
from scripts.audit_upstream import DEFAULT_SOURCE


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    files = {f"rc_fold_{i}": (f"outputs/result/shearwall_pred/0126_cond_kfold/fold_{i}/best_model.pth",
                              f"checkpoints/rcgnn/fold_{i}.pth") for i in range(5)}
    files.update({
        "feasibility": ("data/parametric/ckpt/baseline_gnn_room_hybrid_h256_screen995_v1/gnn_final_pass.pt", "checkpoints/casino/feasibility.pt"),
        "steel": ("data/parametric/ckpt/steel_gnn_room_lr5e4_b512/gnn_steel.pt", "checkpoints/casino/steel.pt"),
        "reference_dxf": ("data/dxf/fem_raw/L17_101.dxf", "data/local/L17_101.dxf"),
        "reference_native_layout": ("data/dxf/cad_json_data/fem_raw/L17_101.json", "data/local/L17_101_native.json"),
    })
    manifest = Path("configs/local_assets.json")
    destinations = [Path(v[1]) for v in files.values()] + [manifest, Path("data/local/reference_layout.json")]
    if any(p.exists() for p in destinations):
        raise FileExistsError("Assets already exist; imports never overwrite existing local assets")
    if any(not (args.source/relative).is_file() for relative,_ in files.values()):
        raise FileNotFoundError("BLOCKED: required upstream asset missing")
    records = {}
    for name,(relative,dest) in files.items():
        source, target = args.source/relative, Path(dest)
        target.parent.mkdir(parents=True,exist_ok=True)
        with source.open("rb") as src, target.open("xb") as dst:
            shutil.copyfileobj(src,dst)
        records[name] = {"path":str(target), "sha256":sha256(target), "source":str(source)}
        if records[name]["sha256"] != sha256(source):
            raise IOError(f"Copy hash mismatch: {source}")
    layout = read_legacy_layout(Path(files["reference_native_layout"][1]), unit="mm", layout_id="L17_101")
    write_json(Path("data/local/reference_layout.json"),layout.model_dump())
    write_json(manifest,records)
    print(f"Imported {len(records)} assets with matching SHA256; manifest: {manifest}")


if __name__ == "__main__":
    main()
