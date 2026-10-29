from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from struct_agent.adapters.etabs.connection_audit import inspect_connections, analysis_line_connections
from struct_agent.adapters.etabs.contracts import ConnectionAuditSpec, ETABSRequest, ETABSConfig
from struct_agent.io.artifacts import sha256


class ReadOnlyClient:
    def __init__(self) -> None:
        self.operations: list[str] = []
        self.model = SimpleNamespace(File=SimpleNamespace(OpenFile=None),SetPresentUnits=None,
            FrameObj=SimpleNamespace(**{key:None for key in ('GetNameList','GetPoints','GetLocalAxes',
                'GetInsertionPoint','GetEndLengthOffset','GetReleases','GetSection')}),
            PointObj=SimpleNamespace(GetCoordCartesian=None))

    def call(self, operation: str, method: Any, *args: Any) -> tuple[Any,...]:
        self.operations.append(operation)
        values = {'ConnectionFrameNames':(1,['B1']), 'ConnectionEndPoints':('P1','P2'),
            'ConnectionNodeCoord':(0.,0.,2.9), 'ConnectionLocalAxes':(0.,False),
            'ConnectionInsertion':(5,False,False,[0.]*3,[0.]*3,'Global'),
            'ConnectionOffsets':(False,0.,0.,0.),
            'ConnectionReleases':([False]*6,[False]*6,[0.]*6,[0.]*6),
            'ConnectionSection':('primary','')}
        return values.get(operation,())


def test_connection_audit_has_no_analysis_save_or_source_mutation(tmp_path: Path) -> None:
    source = tmp_path/'source.EDB'
    source.write_bytes(b'explicit synthetic EDB bytes for read-only contract test')
    source.with_suffix('.Y_').write_bytes(b'synthetic cache bytes')
    spec = ConnectionAuditSpec(model=source,model_sha256=sha256(source))
    directory = tmp_path/'audit'
    directory.mkdir()
    client = ReadOnlyClient()
    result = inspect_connections(client,spec,directory)
    assert result['verified'] and result['source_unchanged'] and result['copy_unchanged']
    assert result['source_caches_unchanged'] and len(result['source_cache_hashes']) == 1
    assert (directory/'inspection.Y_').read_bytes() == b'synthetic cache bytes'
    assert not result['analysis_called'] and not result['save_called']
    assert client.operations[0] == 'OpenCopiedDiagnostic'
    assert all('Save' not in operation and 'Analysis' not in operation for operation in client.operations)


def test_audit_refuses_unbound_input_before_opening_model(tmp_path: Path) -> None:
    source = tmp_path/'source.EDB'
    source.write_bytes(b'synthetic')
    client = ReadOnlyClient()
    with pytest.raises(ValueError,match='hash mismatch'):
        inspect_connections(client,ConnectionAuditSpec(model=source,model_sha256='0'*64),tmp_path)
    assert not client.operations


def test_audit_request_roundtrip_and_path_scope(tmp_path: Path) -> None:
    spec = ConnectionAuditSpec(model=tmp_path/'source.EDB',model_sha256='0'*64)
    request = ETABSRequest(config=ETABSConfig(),spec=spec)
    assert ETABSRequest.model_validate_json(request.model_dump_json()) == request
    for path in (Path('relative.EDB'), tmp_path/'not_edb.txt'):
        with pytest.raises(ValueError):
            ConnectionAuditSpec(model=path,model_sha256='0'*64)


def test_resolved_analysis_offsets_do_not_use_automatic_object_placeholders() -> None:
    client = ReadOnlyClient()
    client.model.FrameObj.GetElm = None
    client.model.LineElm = SimpleNamespace(GetEndLengthOffset=None,GetInsertionPoint=None)
    def call(operation: str, method: Any, *args: Any) -> tuple[Any,...]:
        return {'ConnectionAnalysisElements':(1,['line1'],[0.],[1.]),
            'ConnectionResolvedOffsets':(.25,0.,.5),
            'ConnectionResolvedInsertion':([0.]*3,[0.]*3)}[operation]
    client.call = call
    result = analysis_line_connections(client,['B1'])
    assert not result['all_resolved_end_lengths_zero']
    assert result['frames']['B1'][0]['end_length_offsets_m_and_rz'][0] == .25


def test_read_only_audit_can_select_frames_and_read_preexisting_analysis_elements(tmp_path: Path) -> None:
    source = tmp_path/'source.EDB'
    source.write_bytes(b'synthetic')
    directory = tmp_path/'audit'
    directory.mkdir()
    client = ReadOnlyClient()
    original_call = client.call
    client.model.Analyze = SimpleNamespace(CreateAnalysisModel=None)
    client.model.FrameObj.GetElm = None
    client.model.LineElm = SimpleNamespace(GetEndLengthOffset=None,GetInsertionPoint=None)
    def call(operation: str, method: Any, *args: Any) -> tuple[Any,...]:
        values = {'ConnectionAnalysisElements':(1,['line1'],[0.],[1.]),
            'ConnectionResolvedOffsets':(.1,0.,.5),'ConnectionResolvedInsertion':([0.]*3,[0.]*3)}
        return values[operation] if operation in values else original_call(operation,method,*args)
    client.call = call
    result = inspect_connections(client,ConnectionAuditSpec(model=source,model_sha256=sha256(source),
        frame_names=('B1',),read_generated_lines=True),directory)
    assert not result['generated_lines']['all_resolved_end_lengths_zero']
    assert result['analysis_model_generated_on_copy']
    assert not result['analysis_called'] and not result['save_called']
    with pytest.raises(ValueError,match='Unknown or duplicate'):
        inspect_connections(client,ConnectionAuditSpec(model=source,model_sha256=sha256(source),
            frame_names=('unknown',)),tmp_path)
    changed = tmp_path/'changed'
    changed.mkdir()
    def modifying_call(operation: str, method: Any, *args: Any) -> tuple[Any,...]:
        if operation == 'CreateCopiedAnalysisModel':
            (changed/'inspection.EDB').write_bytes(b'unexpected graph-generation model mutation')
        return call(operation,method,*args)
    client.call = modifying_call
    with pytest.raises(ValueError,match='changed a model file'):
        inspect_connections(client,ConnectionAuditSpec(model=source,model_sha256=sha256(source),
            read_generated_lines=True),changed)
