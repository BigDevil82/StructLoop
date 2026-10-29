"""Fixed ETABS verification worker. No caller scripts, commands or session attach."""
from __future__ import annotations

from pathlib import Path
import sys
import traceback

from struct_agent.io.artifacts import write_json
from struct_agent.schemas import ErrorRecord
from .benchmark import build_and_analyze
from .client import session
from .contracts import ETABSRequest, CantileverSpec, SingleWallSpec


def main() -> int:
    directory = Path.cwd()
    try:
        request = ETABSRequest.model_validate_json(sys.stdin.buffer.read())
        config, spec = request.config, request.spec
        print('STAGE dedicated_application_start', flush=True)
        with session(config.install_root, directory) as client:
            version = client.call('GetVersion', client.model.GetVersion)
            print('STAGE build_and_analyze', flush=True)
            if isinstance(spec,CantileverSpec):
                result = build_and_analyze(client, spec, directory)
            elif isinstance(spec, SingleWallSpec):
                from .wall_etabs import build_and_analyze as single_wall
                result = single_wall(client, spec, directory)
            else:
                from .residential import build_and_analyze as residential
                result = residential(client,spec,directory,beam_theory=config.beam_theory,
                    wall_vertical_subdivisions=config.wall_vertical_subdivisions)
        write_json(directory/'worker_result.json', {'status':'SUCCESS' if result['verified'] else 'INVALID_RESULT',
            'version':version, 'result':result})
        print('STAGE result_saved', flush=True)
        return 0
    except Exception as error:
        record = ErrorRecord(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc(),
            context={'operation':'ETABS verification','directory':str(directory)},attempt=1)
        write_json(directory/'worker_error.json', record.model_dump())
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
