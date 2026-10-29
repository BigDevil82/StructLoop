import pytest

from struct_agent.adapters.etabs.contracts import ResidentialSpec
from struct_agent.adapters.etabs.membrane_patch import membrane_patch
from struct_agent.schemas import ProjectSpec,LayoutCandidate,DesignCandidate


@pytest.mark.real
def test_affine_strain_distinguishes_macro_response_from_continuum_poisson_coupling(
        spec: ProjectSpec,layout: LayoutCandidate,design: DesignCandidate) -> None:
    parent = ResidentialSpec(project=spec.model_copy(update={'stories':12}),layout=layout,design=design)
    macro,shell = (membrane_patch(parent,name) for name in ('mvlem','shell_dkgq'))
    assert macro['verified'] and shell['verified']
    restrained = shell['cases'][1]
    assert restrained['plane_stress_equivalent']
    assert restrained['measured_stress_xx_zz_pa'][1]>0.
    assert not macro['cases'][1]['plane_stress_equivalent']
    assert abs(macro['cases'][1]['measured_stress_xx_zz_pa'][1])<1e-5
    assert macro['cases'][1]['measured_stress_xx_zz_pa'][0]==pytest.approx(2*macro['E_pa']*1e-5)
    # Both elements actively respond to prescribed vertical extension; a
    # zero material state caused by an invalid patch setup cannot pass.
    assert macro['cases'][0]['measured_stress_xx_zz_pa'][1]==pytest.approx(macro['E_pa']*1e-5)
