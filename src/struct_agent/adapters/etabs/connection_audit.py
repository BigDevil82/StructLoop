"""Fixed read-only API queries; no attach, analysis, save or source mutation."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from struct_agent.io.artifacts import sha256, write_json
from .client import ETABSClient
from .contracts import ConnectionAuditSpec, ETABSConfig
from .runtime import run_verification


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
    frames = {}
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
    result = {'purpose':'READ_ONLY_CONNECTION_AUDIT','verified':True,'units':'N_m_kg_s',
        'frames':frames,'source_unchanged':sha256(spec.model) == spec.model_sha256,
        'copy_unchanged':sha256(copy) == spec.model_sha256,
        'source_cache_hashes':caches,
        'source_caches_unchanged':all(sha256(Path(path)) == digest for path,digest in caches.items()),
        'analysis_called':False,'save_called':False,'engineering_feasibility':'NOT_EVALUATED'}
    if not result['source_unchanged'] or not result['copy_unchanged'] or not result['source_caches_unchanged']:
        raise ValueError('Read-only inspection changed a model file')
    write_json(directory/'connections.json',result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--run',type=Path,required=True)
    args = parser.parse_args()
    model = args.model.resolve()
    result = run_verification(ConnectionAuditSpec(model=model,model_sha256=sha256(model)),
        args.run,ETABSConfig(timeout_s=180.))
    print(result['status'])
    if result['status'] != 'SUCCESS':
        raise RuntimeError('Read-only connection audit failed; inspect retained worker error')


if __name__ == '__main__':
    main()
