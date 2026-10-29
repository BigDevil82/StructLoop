"""Synthetic subprocess outcomes; no YJK solver or engineering data is mocked as real."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from struct_agent.adapters import yjk_runtime as runtime
from struct_agent.io.artifacts import sha256, write_json


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, runtime.YJKRuntimeConfig]:
    install = tmp_path/'FAKE_SDK_TEST_ONLY'
    (install/'python310/site-packages/YJKAPI').mkdir(parents=True)
    (install/'python310/python.exe').write_bytes(b'NEVER_EXECUTE_TEST_STUB')
    (install/'python310/site-packages/YJKAPI/__init__.py').write_text('', encoding='utf-8')
    model = tmp_path/'synthetic_model.ydb'
    with sqlite3.connect(model) as connection:
        for table in runtime.COUNTS.values():
            connection.execute(f'CREATE TABLE {table} (ID INTEGER)')
            connection.execute(f'INSERT INTO {table} VALUES (1)')
    return model, runtime.YJKRuntimeConfig(install_root=install, timeout_s=1.)


@pytest.mark.parametrize('exit_code', [3221225477, -1073741819])
def test_native_access_violation_retains_logs_and_never_mutates_source(inputs: tuple, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, exit_code: int) -> None:
    model, cfg = inputs
    before = sha256(model)
    monkeypatch.setattr(runtime, '_execute_worker', lambda *args: subprocess.CompletedProcess(
        [], exit_code, b'STAGE model_read\n', b'native diagnostic'))
    out = tmp_path/'native_exit'
    result = runtime.probe_model_read(model, out, cfg)
    assert result.status == 'PROCESS_ERROR' and result.exit_code_hex == '0xC0000005'
    assert result.error.error_type == 'ChildProcessError' and result.error.attempt == 1
    assert (out/'stdout.log').read_bytes() == b'STAGE model_read\n'
    assert (out/'stderr.log').read_bytes() == b'native diagnostic'
    assert sha256(model) == before and not result.commercial_solver_called
    with pytest.raises(FileExistsError):
        runtime.probe_model_read(model, out, cfg)


def test_timeout_retains_partial_output(inputs: tuple, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args: object) -> None:
        raise subprocess.TimeoutExpired(['fixed-worker'], 1., output=b'partial', stderr=b'waiting')
    monkeypatch.setattr(runtime, '_execute_worker', timeout)
    model, cfg = inputs
    result = runtime.probe_model_read(model, tmp_path/'timeout', cfg)
    assert result.status == 'TIMEOUT' and result.returncode is None and result.error.error_type == 'TimeoutExpired'
    assert (tmp_path/'timeout/stdout.log').read_bytes() == b'partial'


@pytest.mark.parametrize('response', ['missing', 'different_counts', 'boolean_counts', 'valid'])
def test_exit_zero_requires_matching_typed_response(inputs: tuple, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, response: str) -> None:
    def execute(python: Path, worker: Path, directory: Path, timeout: float) -> subprocess.CompletedProcess:
        counts = json.loads((directory/'expected_counts.json').read_text(encoding='utf-8'))
        if response == 'different_counts':
            counts['joints'] += 1
        if response == 'boolean_counts':
            counts['joints'] = True
        if response != 'missing':
            write_json(directory/'worker_response.json', {'model_counts':counts})
        return subprocess.CompletedProcess([], 0, b'worker stopped', b'')
    monkeypatch.setattr(runtime, '_execute_worker', execute)
    model, cfg = inputs
    result = runtime.probe_model_read(model, tmp_path/response, cfg)
    assert result.status == ('SDK_READ_COUNTS_MATCH' if response == 'valid' else 'INVALID_RESPONSE')
    assert not result.commercial_solver_called


@pytest.mark.parametrize('operation', ['arbitrary_shell', 'read_model'])
def test_worker_rejects_unknown_operation_and_external_file_before_loading_sdk(tmp_path: Path, operation: str) -> None:
    worker = Path(runtime.__file__).with_name('yjk_read_worker.py').resolve()
    external = tmp_path/'outside.ydb'
    external.write_bytes(b'TEST_ONLY')
    work = tmp_path/'work'
    work.mkdir()
    result = subprocess.run([sys.executable, str(worker)], cwd=work,
        input=json.dumps({'operation':operation,'model_file':str(external)}).encode(), capture_output=True, timeout=10.)
    assert result.returncode != 0 and b'ValueError' in result.stderr
    assert b'STAGE sdk_import' not in result.stdout
