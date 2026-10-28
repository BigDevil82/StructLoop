from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from struct_agent._vendor.shearwall_modeling.design.constants import ReinforcementDesignConstants
from struct_agent._vendor.shearwall_modeling.parametric.space import split_stories
CONCRETE_PRICE_PER_M3 = {'C30': 500.0, 'C35': 530.0, 'C40': 560.0, 'C45': 590.0, 'C50': 620.0}

@dataclass(frozen=True)
class CostBreakdown:
    concrete_kg: float
    steel_kg: float
    concrete_cost: float
    steel_cost: float
    material_cost: float

def estimate_concrete_kg(row: dict[str, Any], density_kg_m3: float | None=None) -> float:
    density = ReinforcementDesignConstants().concrete_density_kg_m3 if density_kg_m3 is None else density_kg_m3
    n_bot, n_mid, n_top = split_stories(int(row['N']))
    h_story = float(row.get('h_story', 2.9))
    wall_len = float(row['wall_total_length'])
    wall_thickness_sum = n_bot * float(row['tw_bot']) / 1000.0 + n_mid * float(row['tw_mid']) / 1000.0 + n_top * float(row['tw_top']) / 1000.0
    wall_concrete = wall_len * h_story * wall_thickness_sum * density
    main_beam = float(row['main_beam_total_length']) * float(row['bb_main']) / 1000.0 * float(row['hb_main']) / 1000.0 * int(row['N']) * density
    sec_beam = float(row['sec_beam_total_length']) * float(row['bb_sec']) / 1000.0 * float(row['hb_sec']) / 1000.0 * int(row['N']) * density
    return float(wall_concrete + main_beam + sec_beam)

def concrete_unit_price_per_kg(row: dict[str, Any]) -> float:
    price_bot = _price_per_kg(str(row.get('conc_bot', 'C30')))
    price_mid = _price_per_kg(str(row.get('conc_mid', row.get('conc_bot', 'C30'))))
    price_top = _price_per_kg(str(row.get('conc_top', row.get('conc_bot', 'C30'))))
    tw_bot = float(row['tw_bot'])
    tw_mid = float(row['tw_mid'])
    tw_top = float(row['tw_top'])
    total = max(1.0, tw_bot + tw_mid + tw_top)
    return float((tw_bot * price_bot + tw_mid * price_mid + tw_top * price_top) / total)

def material_cost(*, concrete_kg: float, steel_kg: float, row: dict[str, Any], steel_price_per_kg: float) -> CostBreakdown:
    concrete_cost = concrete_unit_price_per_kg(row) * float(concrete_kg)
    steel_cost = float(steel_price_per_kg) * float(steel_kg)
    return CostBreakdown(concrete_kg=float(concrete_kg), steel_kg=float(steel_kg), concrete_cost=float(concrete_cost), steel_cost=float(steel_cost), material_cost=float(concrete_cost + steel_cost))

def _price_per_kg(grade: str) -> float:
    key = grade.strip().upper()
    if not key.startswith('C'):
        key = f'C{key}'
    return CONCRETE_PRICE_PER_M3.get(key, CONCRETE_PRICE_PER_M3['C30']) / 2400.0
