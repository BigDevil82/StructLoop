from typing import List, Tuple
from shapely.affinity import rotate, scale
from shapely.geometry import Polygon

class GeometryAugmentor:
    """
    几何增广器：对房间和墙体多边形进行几何变换
    """

    @staticmethod
    def flip_horizontal(polys: List[Polygon]) -> List[Polygon]:
        """水平翻转 (左右镜像)"""
        return [scale(p, xfact=-1.0, yfact=1.0, origin=(0, 0)) for p in polys]

    @staticmethod
    def flip_vertical(polys: List[Polygon]) -> List[Polygon]:
        """垂直翻转 (上下镜像)"""
        return [scale(p, xfact=1.0, yfact=-1.0, origin=(0, 0)) for p in polys]

    @staticmethod
    def rotate_90(polys: List[Polygon]) -> List[Polygon]:
        """逆时针旋转 90 度"""
        return [rotate(p, angle=90, origin=(0, 0)) for p in polys]

    @staticmethod
    def rotate_180(polys: List[Polygon]) -> List[Polygon]:
        """旋转 180 度"""
        return [rotate(p, angle=180, origin=(0, 0)) for p in polys]

    @staticmethod
    def rotate_270(polys: List[Polygon]) -> List[Polygon]:
        """逆时针旋转 270 度"""
        return [rotate(p, angle=270, origin=(0, 0)) for p in polys]

    @staticmethod
    def apply_augmentation(rooms: List[Polygon], shear_walls: List[Polygon], infill_walls: List[Polygon], mode: str) -> Tuple[List[Polygon], List[Polygon], List[Polygon]]:
        """
        统一应用变换
        mode: 'none', 'flip_x', 'flip_y', 'rot_90', 'rot_180', 'rot_270'
        """
        if mode == 'none':
            return (rooms, shear_walls, infill_walls)
        ops = {'none': None, 'flip_x': GeometryAugmentor.flip_horizontal, 'flip_y': GeometryAugmentor.flip_vertical, 'rot_90': GeometryAugmentor.rotate_90, 'rot_180': GeometryAugmentor.rotate_180, 'rot_270': GeometryAugmentor.rotate_270}
        func = ops.get(mode)
        if not func:
            return (rooms, shear_walls, infill_walls)
        new_rooms = func(rooms)
        new_sw = func(shear_walls)
        new_infill = func(infill_walls)
        return (new_rooms, new_sw, new_infill)
