from dataclasses import replace
import math
import numpy as np
from scipy.optimize import least_squares
from shapely import affinity
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from ..core.config import MaterialConfig
from .constants import CONCRETE_COMPRESSIVE_STRENGTH_MPA, CONCRETE_TENSILE_STRENGTH_MPA, ReinforcementDesignConstants, effective_depth_m
from .results import (MaterialUsage, WallDesignDemand, WallReinforcementResult,
    CompoundWallDesignDemand, CompoundWallReinforcementResult, SectionEquilibrium)


def section_fibers(polygon: BaseGeometry, spacing_mm: float) -> np.ndarray:
    """Area-exact clipped cells: float64 [n,3]=(x,y,area), local mm/mm²."""
    if spacing_mm<=0:
        raise ValueError('Positive section integration spacing required')
    xmin,ymin,xmax,ymax=polygon.bounds
    cells=[]
    for x in np.arange(xmin,xmax,spacing_mm):
        for y in np.arange(ymin,ymax,spacing_mm):
            cell=polygon.intersection(box(x,y,min(x+spacing_mm,xmax),min(y+spacing_mm,ymax)))
            if cell.area>1e-8:
                cells.append((cell.centroid.x,cell.centroid.y,cell.area))
    result=np.asarray(cells,dtype=np.float64).reshape(-1,3)
    if not len(result) or not math.isclose(float(result[:,2].sum()),polygon.area,rel_tol=1e-8):
        raise ValueError('Incomplete section integration area')
    return result


def concrete_response(strain: np.ndarray, fc_mpa: float) -> tuple[np.ndarray,np.ndarray]:
    """GB50010 C30-C50 compression law; no tensile concrete, tangent in MPa."""
    ratio=np.clip(strain/.002,0.,1.)
    stress=fc_mpa*(2*ratio-ratio**2)
    tangent=np.where((strain>0)&(strain<.002),fc_mpa*1000*(1-ratio),0.)
    return stress,tangent


def section_equilibrium(concrete: np.ndarray, steel: np.ndarray, steel_area: np.ndarray,
                        target: tuple[float,float,float], fc_mpa: float, fy_mpa: float,
                        label: str) -> SectionEquilibrium:
    """Solve plane strain for signed (N,Mx,My), N/N*m. Compression positive.

    Steel replaces concrete at its integration positions. No independent N/M
    extrema are silently treated as concurrent forces; cases identify envelopes.
    """
    radius=max(float(np.ptp(concrete[:,:2],axis=0).max()),1.)
    def basis(points: np.ndarray) -> np.ndarray:
        return np.column_stack((np.ones(len(points)),points[:,1]/radius,-points[:,0]/radius))
    bc,bs=basis(concrete),basis(steel)
    scale=fc_mpa*float(concrete[:,2].sum())
    demand=np.asarray((target[0],target[1]*1000/radius,target[2]*1000/radius))
    def evaluate(q: np.ndarray) -> tuple[np.ndarray,np.ndarray]:
        ec,es=bc@q,bs@q
        sc,tc=concrete_response(ec,fc_mpa);cs,ct=concrete_response(es,fc_mpa)
        ss=np.clip(200000*es,-fy_mpa,fy_mpa)
        st=np.where(np.abs(es)<fy_mpa/200000,200000.,0.)
        force=bc.T@(sc*concrete[:,2])+bs.T@((ss-cs)*steel_area)
        tangent=bc.T@((tc*concrete[:,2])[:,None]*bc)+bs.T@(((st-ct)*steel_area)[:,None]*bs)
        # Edge vertices are included by the caller as zero-area concrete points.
        ic=int(np.argmax(ec));its=int(np.argmin(es))
        residual=np.r_[(force-demand)/scale,max(0.,ec[ic]-.0033)/.0033,max(0.,-.01-es[its])/.01]
        jac=np.vstack((tangent/scale,bc[ic]/.0033 if ec[ic]>.0033 else np.zeros(3),
                       -bs[its]/.01 if es[its]<-.01 else np.zeros(3)))
        return residual,jac
    elastic=bc.T@((fc_mpa/.002*concrete[:,2])[:,None]*bc)+bs.T@((200000*steel_area)[:,None]*bs)
    initial=np.linalg.solve(elastic,demand)
    solutions=[]
    for start in (initial,np.zeros(3)):
        fit=least_squares(lambda q:evaluate(q)[0],start,jac=lambda q:evaluate(q)[1],
            x_scale=.001,ftol=1e-10,xtol=1e-10,gtol=1e-10,max_nfev=120)
        solutions.append(fit)
        if np.max(np.abs(evaluate(fit.x)[0]))<1e-7:
            break
    fit=min(solutions,key=lambda f:float(np.linalg.norm(evaluate(f.x)[0])))
    residual=evaluate(fit.x)[0]
    error=float(np.max(np.abs(residual[:3])))
    ec,es=bc@fit.x,bs@fit.x
    actual=demand+residual[:3]*scale
    return SectionEquilibrium(label,target,(float(actual[0]),float(actual[1]*radius/1000),float(actual[2]*radius/1000)),
        error,float(ec.max()),float(es.min()),bool(error<1e-6 and ec.max()<=.00330001 and es.min()>=-.01000001))


def design_compound_section(demand: CompoundWallDesignDemand, material: MaterialConfig,
                            constants: ReinforcementDesignConstants, *, spacing_mm: float=20.) -> CompoundWallReinforcementResult:
    """Joint N-Mx-My design with shared boundary steel counted only once.

    Continuous steel areas, not a bar-detailing drawing. Full physical connected
    section uses the plane-section assumption; no artificial flange is added.
    """
    section=demand.section;cx,cy=section.centroid
    polygon=affinity.scale(affinity.translate(section.polygon,-cx,-cy),1000,1000,origin=(0,0))
    boundary=affinity.scale(affinity.translate(section.boundary,-cx,-cy),1000,1000,origin=(0,0))
    concrete=section_fibers(polygon,spacing_mm)
    vertices=np.asarray([(x,y,0.) for x,y in polygon.exterior.coords])
    concrete=np.vstack((concrete,vertices))
    inner=polygon.buffer(-constants.cover_to_centroid_mm)
    inner_boundary=inner.intersection(boundary)
    if inner_boundary.is_empty:
        raise ValueError(f'No room for covered boundary reinforcement: {section.wall_ids}')
    bars_boundary=section_fibers(inner_boundary,spacing_mm)
    inside_web=inner.difference(boundary)
    bars_web=section_fibers(inside_web,spacing_mm) if inside_web.area>1e-8 else np.empty((0,3))
    steel=np.vstack((bars_boundary,bars_web))
    boundary_weights=bars_boundary[:,2]/bars_boundary[:,2].sum()*boundary.area
    web_area=max(0.,polygon.area-boundary.area)
    # Very short sections can have all their area assigned to shared boundaries.
    if web_area>1e-6 and not len(bars_web):
        raise ValueError('No covered integration region for distributed bars')
    web_weights=bars_web[:,2]/bars_web[:,2].sum()*web_area if len(bars_web) else np.empty(0)
    fc,_=_resolve_fc_ft(material)
    axial=max(max(0.,n) for _,n,_,_,_ in demand.load_cases)/(fc*polygon.area)
    constrained=axial>(.3 if section.story<=2 else .4)
    minimum=constants.boundary_constrained_min_ratio if constrained else constants.boundary_constructive_min_ratio
    distributed=max(.0025,constants.wall_vertical_min_ratio)
    targets=[(name,tuple(factor*v for v in (n,mx,my))) for name,n,mx,my,seismic in demand.load_cases
             for factor in (constants.gamma_re_wall if seismic else 1.,)]
    def check(rho: float) -> tuple[SectionEquilibrium,...]:
        areas=np.r_[rho*boundary_weights,distributed*web_weights]
        return tuple(section_equilibrium(concrete,steel,areas,target,fc,constants.fy_mpa,name) for name,target in targets)
    rho=minimum;checks=check(rho)
    if not all(c.passed for c in checks):
        upper=.04;upper_checks=check(upper)
        if all(c.passed for c in upper_checks):
            lower=minimum
            for _ in range(9):
                middle=(lower+upper)/2;trial=check(middle)
                if all(c.passed for c in trial):upper,upper_checks=middle,trial
                else:lower=middle
        rho,checks=upper,upper_checks
    passed=all(c.passed for c in checks) and axial<=demand.axial_limit
    messages=[]
    if not all(c.passed for c in checks):messages.append('compound_equilibrium_or_strain_limit_not_satisfied')
    if axial>demand.axial_limit:messages.append('compound_axial_ratio_exceeded')
    if section.kind=='column':
        passed=False;messages.append('column_stability_and_detailing_review_required')
    return CompoundWallReinforcementResult(section.section_id,section.story,section.wall_ids,section.kind,section.centroid,
        polygon.area/1e6,boundary.area/1e6,float(rho*boundary.area+distributed*web_area),rho,distributed,axial,
        demand.axial_limit,passed,checks,tuple(messages))

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
