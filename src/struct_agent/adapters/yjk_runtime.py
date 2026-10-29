"""Isolated SDK model-read probe, not a validated YJK analysis adapter."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3
import subprocess
import time
import traceback
from typing import Literal

from pydantic import Field

from struct_agent.io.artifacts import create_run, sha256, write_json
from struct_agent.schemas import ErrorRecord
from struct_agent.schemas.base import Contract

COUNTS = {'joints':'tblJoint', 'grids':'tblGrid', 'standard_floors':'tblStdFlr',
          'floors':'tblFloor', 'walls':'tblWallSeg', 'beams':'tblBeamSeg', 'slabs':'tblSlab'}
logger = logging.getLogger(__name__)


class YJKRuntimeConfig(Contract):
    install_root: Path
    timeout_s: float = Field(default=30., gt=0., le=120.)


class YJKProbeOutcome(Contract):
    status: Literal['SDK_READ_COUNTS_MATCH', 'PROCESS_ERROR', 'TIMEOUT', 'INVALID_RESPONSE']
    returncode: int | None
    exit_code_hex: str | None
    elapsed_s: float = Field(ge=0.)
    model_counts: dict[str, int] | None = None
    error: ErrorRecord | None
    commercial_solver_called: Literal[False] = False


def _execute_worker(python: Path, worker: Path, directory: Path, timeout: float) -> subprocess.CompletedProcess[bytes]:
    """Fixed worker and operation; never pass caller code, shell or SDK commands."""
    request = json.dumps({'operation':'read_model','model_file':str(directory/'project/dtlmodel.ydb')}).encode()
    return subprocess.run([str(python), '-u', str(worker)], input=request, cwd=directory,
        capture_output=True, timeout=timeout, shell=False,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def probe_model_read(model: Path, directory: Path, config: YJKRuntimeConfig) -> YJKProbeOutcome:
    """Read a copied model in a disposable SDK process; preserve native failures.

    SDK success requires actual table counts to match the source. It does not
    certify engineering input or prove an unattended solver/GUI host lifecycle.
    """
    model, directory = model.resolve(), directory.resolve()
    python = config.install_root.resolve()/'python310/python.exe'
    sdk = config.install_root.resolve()/'python310/site-packages/YJKAPI/__init__.py'
    worker = Path(__file__).with_name('yjk_read_worker.py').resolve()
    if not model.is_file() or not python.is_file() or not sdk.is_file():
        raise FileNotFoundError('BLOCKED: model or installed YJK SDK runtime missing')
    create_run(directory, seed=0, inputs={'model':model,'python':python,'sdk':sdk,'worker':worker},
        config={'operation':'read_model','timeout_s':config.timeout_s,'commercial_solver_calls':0})
    (directory/'project').mkdir()
    target = directory/'project/dtlmodel.ydb'
    # Consistent SQLite snapshot, including a committed WAL if one is present.
    with sqlite3.connect(model.as_uri()+'?mode=ro', uri=True) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    # Compare with the exact snapshot the worker receives, even if the source changes.
    with sqlite3.connect(target.as_uri()+'?mode=ro', uri=True) as connection:
        expected = {name:connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                    for name, table in COUNTS.items()}
    write_json(directory/'expected_counts.json', expected)
    started, code, stdout, stderr, error = time.monotonic(), None, b'', b'', None
    status, counts = 'PROCESS_ERROR', None
    try:
        process = _execute_worker(python, worker, directory, config.timeout_s)
        code, stdout, stderr = process.returncode, process.stdout, process.stderr
        if code != 0:
            raise ChildProcessError(f'YJK SDK process exited {code} (0x{code & 0xffffffff:08X})')
        status = 'INVALID_RESPONSE'
        data = json.loads((directory/'worker_response.json').read_text(encoding='utf-8'))
        if set(data) != {'model_counts'} or data['model_counts'] != expected:
            raise ValueError('SDK read counts differ from source model')
        if any(type(v) is not int or v < 0 for v in data['model_counts'].values()):
            raise ValueError('SDK returned invalid model counts')
        counts, status = data['model_counts'], 'SDK_READ_COUNTS_MATCH'
    except subprocess.TimeoutExpired as exc:
        status, stdout, stderr = 'TIMEOUT', exc.stdout or b'', exc.stderr or b''
        error = ErrorRecord(error_type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc(),
            context={'operation':'read_model','model':str(model)}, attempt=1)
    except Exception as exc:
        error = ErrorRecord(error_type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc(),
            context={'operation':'read_model','model':str(model),
                     'native_traceback':'No native Python traceback is implied by this parent traceback.'}, attempt=1)
    (directory/'stdout.log').write_bytes(stdout)
    (directory/'stderr.log').write_bytes(stderr)
    outcome = YJKProbeOutcome(status=status, returncode=code,
        exit_code_hex=None if code is None else f'0x{code & 0xffffffff:08X}', elapsed_s=time.monotonic()-started,
        model_counts=counts, error=error)
    write_json(directory/'outcome.json', outcome.model_dump())
    write_json(directory/'snapshot.json', {'model_snapshot_sha256':sha256(target),
        'source_after_sha256':sha256(model), 'expected_counts':expected})
    logger.info('YJK probe status=%s exit=%s elapsed=%.3fs', status, outcome.exit_code_hex, outcome.elapsed_s)
    return outcome
