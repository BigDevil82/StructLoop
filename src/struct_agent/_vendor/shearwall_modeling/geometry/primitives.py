from ..core.domain import Point2D

def polygon_area(points: list[Point2D]) -> float:
    if len(points) < 3:
        return 0.0
    acc = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        acc += point.x * next_point.y - next_point.x * point.y
    return abs(acc) * 0.5

def segment_length(p1: Point2D, p2: Point2D) -> float:
    return p1.distance_to(p2)

def rect_slab_span_depth(slab: list[Point2D]) -> tuple[float, float] | None:
    if len(slab) != 4:
        return None
    edges = [segment_length(slab[index], slab[(index + 1) % 4]) for index in range(4)]
    if any((edge <= 1e-09 for edge in edges)):
        return None
    tolerance = 0.2
    e0, e1, e2, e3 = edges
    if abs(e0 - e2) / max(e0, e2) > tolerance:
        return None
    if abs(e1 - e3) / max(e1, e3) > tolerance:
        return None
    return (min(edges), max(edges))
