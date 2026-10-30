from dataclasses import replace
import math
from ..core.config import MaterialConfig
from .constants import CONCRETE_COMPRESSIVE_STRENGTH_MPA, CONCRETE_TENSILE_STRENGTH_MPA, ReinforcementDesignConstants, effective_depth_m
from .results import MaterialUsage, WallDesignDemand, WallReinforcementResult

def _resolve_fc_ft(material: MaterialConfig) -> tuple[float, float]:
    grade = material.concrete_grade.strip().upper()
    return (CONCRETE_COMPRESSIVE_STRENGTH_MPA[grade], CONCRETE_TENSILE_STRENGTH_MPA[grade])


def symmetric_boundary_area(axial_n: float, moment_n_mm: float, width_mm: float,
                            length_mm: float, cover_mm: float, fc_mpa: float, fy_mpa: float) -> float:
    """Area at EACH wall end from compatible rectangular-section equilibrium.

    N compression positive; M about the whole wall centroid, N*mm. C30-C50:
    equivalent block beta1=0.8, ultimate strain=0.0033; Es=200000 MPa.
    Distributed vertical bars are omitted from resistance, conservatively.
    """
    moment_n_mm = abs(moment_n_mm)
    lever = length_mm/2-cover_mm
    if min(width_mm,lever,fc_mpa,fy_mpa) <= 0:
        raise ValueError('Invalid wall boundary section')
    if 0<axial_n<=fc_mpa*width_mm*length_mm and moment_n_mm<=axial_n*(length_mm-axial_n/(fc_mpa*width_mm))/2:
        # Inside the unreinforced compression interaction envelope, rather than
        # on its ultimate boundary: minimum reinforcement suffices for N/M.
        return 0.
    if moment_n_mm == 0:
        return max(0.,(abs(axial_n) if axial_n<0 else axial_n-fc_mpa*width_mm*length_mm)/(2*fy_mpa))
    def section(x: float) -> tuple[float,float,float,float]:
        block = min(x,length_mm)
        concrete = fc_mpa*width_mm*block
        stresses = [max(-fy_mpa,min(fy_mpa,200000*.0033*(1-.8*y/x)))
                    for y in (cover_mm,length_mm-cover_mm)]
        return concrete,concrete*(length_mm-block)/2,sum(stresses),(stresses[0]-stresses[1])*lever
    def residual(x: float) -> float:
        c,cm,s,d = section(x)
        return (axial_n-c)*d-(moment_n_mm-cm)*s
    points = [length_mm*10**(-8+10*i/200) for i in range(201)]
    roots = []
    for left,right in zip(points,points[1:]):
        fl,fr = residual(left),residual(right)
        if fl*fr>0:
            continue
        for _ in range(55):
            mid = (left+right)/2
            fm = residual(mid)
            if fl*fm<=0:
                right = mid
            else:
                left,fl = mid,fm
        roots.append((left+right)/2)
    areas = []
    for x in roots:
        c,cm,s,d = section(x)
        area = (moment_n_mm-cm)/d if abs(d)>abs(s)*length_mm else (axial_n-c)/s if s else -1.
        if area>=0 and math.isclose(c+area*s,axial_n,rel_tol=1e-7,abs_tol=.01) and math.isclose(cm+area*d,moment_n_mm,rel_tol=1e-7,abs_tol=1.):
            areas.append(area)
    if not areas:
        raise ValueError(f'No compatible wall section equilibrium: N={axial_n}, M={moment_n_mm}')
    return min(areas)

class WallReinforcementDesigner:

    def __init__(self, constants: ReinforcementDesignConstants | None=None):
        self.constants = constants or ReinforcementDesignConstants()

    def design(self, demand: WallDesignDemand, material: MaterialConfig) -> WallReinforcementResult:
        fc_mpa, ft_mpa = _resolve_fc_ft(material)
        if demand.load_cases:
            results = [self.design(replace(demand,load_cases=(),axial_force_n=n,moment_n_m=m,shear_n=v,
                axial_ratio=max(0.,n)/(fc_mpa*1e6*demand.thickness_m*demand.length_m),
                seismic=seismic,shear_limit=limit),material) for n,m,v,limit,seismic in demand.load_cases]
            result = max(results,key=lambda r:r.material_usage.steel_kg)
            horizontal = max(r.horizontal_distributed_steel_mm2_per_m for r in results)
            vertical = max(r.vertical_distributed_steel_mm2_per_m for r in results)
            longitudinal = max(r.boundary_longitudinal_steel_mm2 for r in results)
            volume_ratio = .006 if any(r.boundary_type=='constrained' for r in results) else .004
            hc = min(max(2*demand.thickness_m,.15*demand.length_m),demand.length_m/2)
            steel = (vertical+horizontal)*1e-6*demand.length_m*demand.story_height_m*self.constants.steel_density_kg_m3
            steel += 2*demand.story_height_m*(longitudinal*1e-6+volume_ratio*demand.thickness_m*hc)*self.constants.steel_density_kg_m3
            return replace(result,horizontal_distributed_steel_mm2_per_m=horizontal,vertical_distributed_steel_mm2_per_m=vertical,
                boundary_longitudinal_steel_mm2=longitudinal,boundary_type='constrained' if volume_ratio==.006 else 'constructive',
                boundary_stirrup_area_mm2=max(r.boundary_stirrup_area_mm2 for r in results),
                boundary_stirrup_spacing_mm=min(r.boundary_stirrup_spacing_mm for r in results),
                material_usage=MaterialUsage(result.material_usage.concrete_kg,steel),
                is_section_insufficient=any(r.is_section_insufficient for r in results),
                messages=sorted({msg for r in results for msg in r.messages}))
        bw_mm = demand.thickness_m * 1000.0
        lw_mm = demand.length_m * 1000.0
        hc_mm = min(max(2.0 * bw_mm, 0.15 * lw_mm),lw_mm/2)
        bc_mm = bw_mm
        h0_mm = effective_depth_m(demand.length_m)*1000.
        min_ratio = max(.0025,self.constants.wall_vertical_min_ratio) if demand.seismic else self.constants.wall_vertical_min_ratio
        vertical_area = min_ratio*bw_mm*1000.
        horizontal_area = self._design_horizontal_distributed_steel(demand, bw_mm, h0_mm, ft_mpa)
        boundary_type = self._resolve_boundary_type(demand.axial_ratio, demand.is_bottom_reinforced_zone)
        boundary_longitudinal, boundary_stirrup_area, boundary_spacing, sec_insufficient, messages = self._design_boundary_steel(demand, bc_mm, hc_mm, h0_mm, fc_mpa, boundary_type)
        if abs(demand.shear_n)>demand.shear_limit*self.constants.beta_c*fc_mpa*bw_mm*h0_mm:
            sec_insufficient = True
            messages.append('wall_shear_section_insufficient')
        concrete_kg = demand.thickness_m * demand.length_m * demand.story_height_m * self.constants.concrete_density_kg_m3
        vertical_kg = vertical_area * demand.length_m * demand.story_height_m * self.constants.steel_density_kg_m3 * 1e-06
        horizontal_kg = horizontal_area * demand.length_m * demand.story_height_m * self.constants.steel_density_kg_m3 * 1e-06
        # Both boundary zones extend vertically through the story. hc is their
        # plan length, never the longitudinal bar length. Use the same transverse
        # volumetric ratio as the existing boundary design, without inventing a
        # hoop layout from its equivalent area field.
        volume_ratio = 0.006 if boundary_type == 'constrained' else 0.004
        boundary_volume_m3 = 2.0 * demand.story_height_m * (
            boundary_longitudinal * 1e-6 + volume_ratio * bc_mm * hc_mm * 1e-6)
        boundary_kg = boundary_volume_m3 * self.constants.steel_density_kg_m3
        return WallReinforcementResult(wall_id=demand.wall_id, story=demand.story, vertical_distributed_steel_mm2_per_m=vertical_area, horizontal_distributed_steel_mm2_per_m=horizontal_area, boundary_longitudinal_steel_mm2=boundary_longitudinal, boundary_stirrup_area_mm2=boundary_stirrup_area, boundary_stirrup_spacing_mm=boundary_spacing, boundary_type=boundary_type, material_usage=MaterialUsage(concrete_kg=concrete_kg, steel_kg=vertical_kg + horizontal_kg + boundary_kg), is_over_reinforced=False, is_section_insufficient=sec_insufficient, messages=messages)

    def _design_horizontal_distributed_steel(self, demand: WallDesignDemand, wall_thickness_mm: float, effective_length_mm: float, ft_mpa: float) -> float:
        spacing_mm = self.constants.wall_horizontal_spacing_mm
        design_shear_n = (self.constants.gamma_re_shear if demand.seismic else 1.) * abs(demand.shear_n)
        shear_span = min(2.2,max(1.5,abs(demand.moment_n_m)*1000/(abs(demand.shear_n)*effective_length_mm))) if demand.shear_n else 2.2
        # Omit beneficial compression; retain adverse tension in the SAME combo.
        concrete = max(0.,(.4*ft_mpa*wall_thickness_mm*effective_length_mm-.13*max(0.,-demand.axial_force_n))/(shear_span-.5))
        steel_area = (design_shear_n-concrete)*spacing_mm/(.8*self.constants.fyv_mpa*effective_length_mm)
        minimum = max(.0025,self.constants.wall_horizontal_min_ratio) if demand.seismic else self.constants.wall_horizontal_min_ratio
        steel_area_per_m = max(steel_area / max(spacing_mm, 1e-09) * 1000.0, minimum*wall_thickness_mm*1000.)
        return steel_area_per_m

    def _resolve_boundary_type(self, axial_ratio: float, is_bottom_reinforced_zone: bool) -> str:
        threshold = 0.3 if is_bottom_reinforced_zone else 0.4
        return 'constrained' if axial_ratio > threshold else 'constructive'

    def _design_boundary_steel(self, demand: WallDesignDemand, boundary_width_mm: float, boundary_height_mm: float, effective_length_mm: float, fc_mpa: float, boundary_type: str) -> tuple[float, float, float, bool, list[str]]:
        messages: list[str] = []
        factor = self.constants.gamma_re_wall if demand.seismic else 1.
        design_axial_n = factor*demand.axial_force_n
        design_moment_n_mm = factor*abs(demand.moment_n_m)*1000.
        b = boundary_width_mm
        h = boundary_height_mm
        h0 = effective_length_mm
        a_s = self.constants.cover_to_centroid_mm
        fy = self.constants.fy_mpa
        max_reinforcement_ratio = .04
        section_insufficient = False
        longitudinal_area = symmetric_boundary_area(design_axial_n,design_moment_n_mm,b,h0+a_s,a_s,fc_mpa,fy)
        min_ratio = self.constants.boundary_constrained_min_ratio if boundary_type == 'constrained' else self.constants.boundary_constructive_min_ratio
        min_area = min_ratio * b * h
        if longitudinal_area < min_area - 1e-06:
            longitudinal_area = min_area
            messages.append('minimum_boundary_longitudinal_steel_governs')
        calculated_ratio = longitudinal_area / (b * h)
        if calculated_ratio > max_reinforcement_ratio:
            section_insufficient = True
            messages.append('boundary_steel_ratio_exceeds_max')
        volume_ratio = 0.006 if boundary_type == 'constrained' else 0.004
        spacing_mm = self.constants.boundary_stirrup_spacing_constrained_mm if boundary_type == 'constrained' else self.constants.boundary_stirrup_spacing_constructive_mm
        stirrup_area = volume_ratio * b * h * spacing_mm / max(self.constants.boundary_stirrup_limb_spacing_mm, 1e-09)
        return (longitudinal_area, stirrup_area, spacing_mm, section_insufficient, messages)
