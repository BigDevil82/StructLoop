"""Python 3.10 vendor-SDK worker. Standard library + installed YJKAPI only."""
from __future__ import annotations

import faulthandler
import json
from pathlib import Path
import sys
import traceback


def main() -> int:
    root = Path.cwd().resolve()
    request = json.loads(sys.stdin.buffer.read().decode('utf-8'))
    if set(request) != {'operation','model_file'} or request['operation'] != 'read_model':
        raise ValueError('Only the fixed model-read probe is permitted')
    model = Path(request['model_file']).resolve()
    if model != root/'project/dtlmodel.ydb' or not model.is_file():
        raise ValueError('Only the isolated project snapshot may be read')
    with (root/'native_fault.log').open('x', encoding='utf-8') as fault:
        faulthandler.enable(file=fault, all_threads=True)
        try:
            print('STAGE sdk_import', flush=True)
            # The installed package interprets argv[1] as its SDK loading mode.
            # Requests travel through stdin so it retains its NDepend default.
            import YJKAPI as sdk
            data = sdk.DataFunc()
            data.SetCurState(sdk.DataFuncState._Default)
            bridge = sdk.Hi_AddToAndReadYjk(data.GetDbModelData())
            print('STAGE model_read', flush=True)
            model_data = bridge.ReadYdb(str(model))
            data.SetModel(model_data)
            counts = {'joints':len(data.GetJointList()), 'grids':len(data.GetGridList()),
                'standard_floors':len(data.GetStdFlrList()), 'floors':len(data.GetFloorList()),
                'walls':len(data.GetWallSegList()), 'beams':len(data.GetBeamSegList()), 'slabs':len(data.GetSlabList())}
            with (root/'worker_response.json').open('x', encoding='utf-8') as stream:
                json.dump({'model_counts':counts}, stream)
            return 0
        except Exception as exc:
            with (root/'worker_error.json').open('x', encoding='utf-8') as stream:
                json.dump({'error_type':type(exc).__name__,'message':str(exc),
                           'traceback':traceback.format_exc()}, stream)
            return 1
        finally:
            faulthandler.disable()


if __name__ == '__main__':
    raise SystemExit(main())
