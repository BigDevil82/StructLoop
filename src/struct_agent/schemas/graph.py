from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .base import Contract


class RoomGraph(Contract):
    """Native RC features retained verbatim; geometry exchanged in global XY m.

    x float32[N,25], edge_index int64[2,E], edge_attr float32[E,8].
    room_polygons float64 variable[N,K,2] m, masks dimensionless[N,8,...].
    Node ordering, normalized features and half-edge ordering follow upstream.
    """
    schema_version: Literal[1] = 1
    feature_version: Literal["rcgnn_25_8_v1"]
    length_unit: Literal["m"]
    native_feature_length_unit: Literal["mm"]
    coordinate_system: Literal["global_xy"]
    x: tuple[tuple[float, ...], ...] = Field(min_length=1)
    edge_index: tuple[tuple[int, ...], tuple[int, ...]]
    edge_attr: tuple[tuple[float, ...], ...]
    room_polygons: tuple[tuple[tuple[float, float], ...], ...]
    masks: tuple[tuple[tuple[tuple[float, float], ...], ...], ...]
    category: Literal[0, 1, 2]

    @model_validator(mode="after")
    def dimensions(self) -> RoomGraph:
        n = len(self.x)
        if any(len(row) != 25 for row in self.x):
            raise ValueError("Expected x[N,25]")
        e = len(self.edge_index[0])
        if len(self.edge_index[1]) != e or len(self.edge_attr) != e:
            raise ValueError("Inconsistent edge count")
        if any(len(row) != 8 for row in self.edge_attr):
            raise ValueError("Expected edge_attr[E,8]")
        if any(i < 0 or i >= n for row in self.edge_index for i in row):
            raise ValueError("edge_index outside node range")
        if len(self.room_polygons) != n or len(self.masks) != n:
            raise ValueError("Geometry/node alignment mismatch")
        if any(len(poly) < 4 for poly in self.room_polygons):
            raise ValueError("Expected rectangular room polygons")
        for mask in self.masks:
            if len(mask) != 8 or any(not 0 <= a <= b <= 1 for intervals in mask for a, b in intervals):
                raise ValueError("Expected 8 half-edge masks with intervals in [0,1]")
        return self
