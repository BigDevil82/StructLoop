"""Supervised external ETABS process; immutable artifacts and owned-instance cleanup."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from struct_agent.io.artifacts import create_run, write_json, sha256
from .contracts import CantileverSpec, ResidentialSpec, SingleWallSpec, StructuralBatchSpec, ConnectionAuditSpec, ConnectionStudySpec, ModelFormReviewSpec, ETABSConfig


def run_verification(spec: CantileverSpec | ResidentialSpec | SingleWallSpec | StructuralBatchSpec | ConnectionAuditSpec | ConnectionStudySpec | ModelFormReviewSpec, directory: Path, config: ETABSConfig) -> dict[str, Any]:
    import psutil
    directory = directory.resolve()
    install = config.install_root.resolve()
    config = config.model_copy(update={'install_root':install})
    executable = install/'ETABS.exe'
    if not executable.is_file() or not (install/'ETABSv1.tlb').is_file():
        raise FileNotFoundError('BLOCKED: ETABS executable/API missing')
    create_run(directory, seed=0, inputs={'executable':executable,'api':install/'ETABSv1.dll'},
        config={'etabs':config.model_dump(mode='json'),'spec':spec.model_dump(mode='json')})
    request = {'config':config.model_dump(mode='json'),'spec':spec.model_dump(mode='json')}
    write_json(directory/'request.json',request)
    # Freeze executed source, including tracebacks, before any long native call.
    package = Path(__file__).resolve().parents[2]
    snapshots = {}
    for file in sorted(package.rglob('*.py')):
        relative = file.relative_to(package.parent)
        target = directory/'source'/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(file.read_bytes())
        snapshots[str(relative)] = sha256(target)
    write_json(directory/'source_snapshot.json',snapshots)
    env = dict(os.environ, PYTHONPATH=str(directory/'source'))
    before = {p.pid for p in psutil.process_iter(['name']) if (p.info['name'] or '').lower() == 'etabs.exe'}
    owned: dict[int, float] = {}
    started = time.monotonic()
    with (directory/'stdout.log').open('xb') as stdout, (directory/'stderr.log').open('xb') as stderr:
        process = subprocess.Popen([sys.executable,'-u','-m','struct_agent.adapters.etabs.worker'],
            cwd=directory,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),shell=False,env=env)
        assert process.stdin is not None
        process.stdin.write(json.dumps(request).encode())
        process.stdin.close()
        parent = psutil.Process(process.pid)
        while process.poll() is None and time.monotonic()-started < config.timeout_s:
            try:
                for child in parent.children(recursive=True):
                    if child.pid not in before and Path(child.exe()).resolve() == executable:
                        owned.setdefault(child.pid,child.create_time())
            except (psutil.NoSuchProcess,psutil.AccessDenied):
                pass
            time.sleep(.2)
        timed_out = process.poll() is None
        if timed_out:
            process.kill()
        process.wait(timeout=10.)
    cleanup = []
    for pid, created in owned.items():
        try:
            child = psutil.Process(pid)
            if child.create_time() != created or Path(child.exe()).resolve() != executable:
                raise RuntimeError('Process ownership changed; refusing cleanup')
            child.terminate()
            child.wait(timeout=10.)
            cleanup.append({'pid':pid,'status':'terminated_owned_process'})
        except psutil.NoSuchProcess:
            cleanup.append({'pid':pid,'status':'already_exited'})
    status = 'TIMEOUT' if timed_out else 'PROCESS_ERROR'
    payload = None
    if not timed_out and process.returncode == 0:
        payload = json.loads((directory/'worker_result.json').read_text(encoding='utf-8'))
        status = payload['status']
    result = {'status':status,'returncode':process.returncode,'elapsed_s':time.monotonic()-started,
        'owned_processes':owned,'cleanup':cleanup,'payload':payload,'engineering_feasibility':'NOT_EVALUATED'}
    write_json(directory/'outcome.json', result)
    return result
