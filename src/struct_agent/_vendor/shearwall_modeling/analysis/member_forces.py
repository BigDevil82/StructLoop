import math
import openseespy.opensees as ops
from ..builders.base import WallStoryElementUnit

def extract_beam_force_tuple(element_tag: int) -> tuple[float, float, float]:
    """
    提取梁单元的基本工况原始内力，严格保留正负号，供后续线性组合使用。
    返回: (i端弯矩, j端弯矩, i端剪力)
    注: 取决于你的 3D 局部坐标系，通常 4,10 是绕主轴弯矩，2,8 是剪力
    """
    force = [float(value) for value in ops.eleForce(element_tag)]
    if len(force) < 12:
        return (0.0, 0.0, 0.0)
    moment_i = force[4]
    moment_j = force[10]
    shear_i = force[2]
    return (moment_i, moment_j, shear_i)

def extract_wall_force_tuple(unit: WallStoryElementUnit, dir_name: str | None) -> tuple[float, float, float]:
    """
    提取墙肢的基本工况截面合力，严格通过节点力积分(代数和)计算，保留正负号。
    返回: (截面合轴力, 截面合弯矩, 截面合剪力)
    """
    node_force_sum: dict[int, list[float]] = {}
    for tag in unit.element_tags:
        values = [float(value) for value in ops.eleResponse(tag, 'forces')]
        if len(values) < 24:
            continue
        ele_nodes = [int(n) for n in ops.eleNodes(tag)][:4]
        for local_index, node in enumerate(ele_nodes[:2]):
            start = local_index * 6
            force_slice = values[start:start + 6]
            node_force_sum.setdefault(node, [0.0] * 6)
            for idx, value in enumerate(force_slice):
                node_force_sum[node][idx] += value
    if not node_force_sum:
        return (0.0, 0.0, 0.0)
    centroid_x = 0.5 * (unit.member.start.x + unit.member.end.x)
    centroid_y = 0.5 * (unit.member.start.y + unit.member.end.y)
    axis_x = unit.member.end.x - unit.member.start.x
    axis_y = unit.member.end.y - unit.member.start.y
    axis_len = max(math.hypot(axis_x, axis_y), 1e-09)
    axis_x /= axis_len
    axis_y /= axis_len
    bend_axis_x = axis_y
    bend_axis_y = -axis_x
    axial_force = 0.0
    bending_moment = 0.0
    shear_force = 0.0
    for node in unit.bottom_nodes:
        values = node_force_sum[node]
        Fx, Fy, Fz, Mx, My, _ = values
        x, y, _ = unit.node_coords[node]
        axial_force += Fz
        dx = x - centroid_x
        dy = y - centroid_y
        lever_moment = dy * Fz * bend_axis_x + -dx * Fz * bend_axis_y
        nodal_moment = Mx * bend_axis_x + My * bend_axis_y
        bending_moment += lever_moment + nodal_moment
        if dir_name == 'X':
            shear_force += Fx
        elif dir_name == 'Y':
            shear_force += Fy
        else:
            shear_force += Fx * axis_x + Fy * axis_y
    return (axial_force, bending_moment, shear_force)
