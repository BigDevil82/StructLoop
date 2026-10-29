from pathlib import Path

import pytest

from struct_agent.adapters.etabs.solver_health import solver_health


@pytest.mark.parametrize('text,expected',[
    ('NUMBER OF NEGATIVE EIGENVALUES = 0\nANALYSIS COMPLETE',True),
    ('NUMBER OF NEGATIVE EIGENVALUES = 2\nANALYSIS COMPLETE',False),
    ('NUMBER OF NEGATIVE EIGENVALUES = 0\n* * * W A R N I N G * * *\nTHE STRUCTURE IS UNSTABLE OR ILL-CONDITIONED !!',False),
    ('ANALYSIS COMPLETE',False),
    ('WARNING: requested modes reduced\nNUMBER OF NEGATIVE EIGENVALUES = 0',True)])
def test_case_completion_and_zero_negative_count_do_not_override_instability(
        tmp_path: Path,text: str,expected: bool) -> None:
    path = tmp_path/'model.LOG'
    path.write_text(text,encoding='utf-8')
    health = solver_health(path)
    assert health['verified'] == expected
    if 'W A R N I N G' in text:
        assert health['warning_markers'] == 1 and health['critical_messages']
