"""Fixed copied-model queries; no attach, solver run, save or source mutation."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

from struct_agent.io.artifacts import sha256, write_json
from .client import ETABSClient
from .contracts import ConnectionAuditSpec, ETABSConfig
from .runtime import run_verification


def analysis_line_connections(client: ETABSClient, names: list[str]) -> dict[str, Any]:
    """Resolved analysis-element offsets, not the object's automatic inputs."""
    m, call = client.model, client.call
    result = {}
    for name in names:
        count, elements, rdi, rdj = call('ConnectionAnalysisElements',m.FrameObj.GetElm,name)
        if count <= 0 or any(len(values) != count for values in (elements,rdi,rdj)):
            raise ValueError('Missing generated analysis line elements')
        lines = []
        for element, start, end in zip(elements,rdi,rdj):
            offsets = call('ConnectionResolvedOffsets',m.LineElm.GetEndLengthOffset,element)
            insertion = call('ConnectionResolvedInsertion',m.LineElm.GetInsertionPoint,element)
            if len(offsets) != 3 or not all(math.isfinite(x) for x in offsets):
                raise ValueError('Invalid resolved analysis offsets')
            lines.append({'element':element,'object_relative_start':start,'object_relative_end':end,
                'end_length_offsets_m_and_rz':offsets,'insertion_offsets_m':insertion})
        result[name] = lines
    if not result:
        raise ValueError('No analysis connections requested')
    zero = all(abs(x) <= 1e-10 for lines in result.values() for line in lines
        for x in line['end_length_offsets_m_and_rz'][:2])
    return {'frames':result,'all_resolved_end_lengths_zero':zero}


def inspect_connections(client: ETABSClient, spec: ConnectionAuditSpec, directory: Path) -> dict[str, Any]:
    if sha256(spec.model) != spec.model_sha256:
        raise ValueError('Source diagnostic EDB hash mismatch')
    copy = directory/'inspection.EDB'
    with copy.open('xb') as stream:
        stream.write(spec.model.read_bytes())
    # ETABS tries to load associated result caches even for property queries.
    # Copy them too so OpenFile does not emit a misleading missing-Y_ notice.
    caches = {}
    for cache in sorted(spec.model.parent.glob(spec.model.stem+'.Y*')):
        if cache.is_file():
            target = directory/('inspection'+cache.name[len(spec.model.stem):])
            with target.open('xb') as stream:
                stream.write(cache.read_bytes())
            caches[str(cache)] = sha256(cache)
    m, call = client.model, client.call
    call('OpenCopiedDiagnostic',m.File.OpenFile,str(copy))
    call('ConnectionUnits',m.SetPresentUnits,10)
    count, names = call('ConnectionFrameNames',m.FrameObj.GetNameList)
    if count <= 0 or count != len(names):
        raise ValueError('No diagnostic frames to inspect')
    if spec.frame_names is not None:
        if len(set(spec.frame_names)) != len(spec.frame_names) or not set(spec.frame_names).issubset(names):
            raise ValueError('Unknown or duplicate requested frame names')
        names = list(spec.frame_names)
    frames = {}
    sections = {}
    for name in names:
        points = call('ConnectionEndPoints',m.FrameObj.GetPoints,name)
        frames[name] = {
            'end_points':points,
            'coordinates_m':[call('ConnectionNodeCoord',m.PointObj.GetCoordCartesian,p) for p in points],
            'local_axes':call('ConnectionLocalAxes',m.FrameObj.GetLocalAxes,name),
            'insertion':call('ConnectionInsertion',m.FrameObj.GetInsertionPoint,name),
            'end_offsets':call('ConnectionOffsets',m.FrameObj.GetEndLengthOffset,name),
            'end_releases':call('ConnectionReleases',m.FrameObj.GetReleases,name),
            'section':call('ConnectionSection',m.FrameObj.GetSection,name)}
        if spec.detailed_axes:
            matrix = call('ConnectionGlobalTransformation',m.FrameObj.GetTransformationMatrix,name)[0]
            if len(matrix) != 9 or not all(math.isfinite(v) for v in matrix):
                raise ValueError('Invalid frame transformation matrix')
            frames[name]['transformation'] = matrix
            prop = frames[name]['section'][0]
            if prop not in sections:
                sections[prop] = call('ConnectionSectionProperties',m.PropFrame.GetSectProps,prop)
    result = {'purpose':'READ_ONLY_CONNECTION_AUDIT','verified':True,'units':'N_m_kg_s',
        'frames':frames,'total_frame_objects':count,'section_properties':sections,
        'source_cache_hashes':caches,
        'analysis_called':False,'save_called':False,'engineering_feasibility':'NOT_EVALUATED'}
    if spec.read_generated_lines:
        # Opening an EDB does not populate FrameObj.GetElm in this ETABS
        # version. Generate the copy's analysis graph, without RunAnalysis.
        call('CreateCopiedAnalysisModel',m.Analyze.CreateAnalysisModel)
        result['analysis_model_generated_on_copy'] = True
        result['generated_lines'] = analysis_line_connections(client,names)
    result.update(source_unchanged=sha256(spec.model) == spec.model_sha256,
        copy_unchanged=sha256(copy) == spec.model_sha256,
        source_caches_unchanged=all(sha256(Path(path)) == digest for path,digest in caches.items()))
    if not result['source_unchanged'] or not result['copy_unchanged'] or not result['source_caches_unchanged']:
        raise ValueError('Read-only inspection changed a model file')
    write_json(directory/'connections.json',result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--read-generated-lines',action='store_true')
    parser.add_argument('--detailed-axes',action='store_true')
    args = parser.parse_args()
    model = args.model.resolve()
    result = run_verification(ConnectionAuditSpec(model=model,model_sha256=sha256(model),
        read_generated_lines=args.read_generated_lines,detailed_axes=args.detailed_axes),
        args.run,ETABSConfig(timeout_s=180.))
    print(result['status'])
    if result['status'] != 'SUCCESS':
        raise RuntimeError('Read-only connection audit failed; inspect retained worker error')


if __name__ == '__main__':
    main()
