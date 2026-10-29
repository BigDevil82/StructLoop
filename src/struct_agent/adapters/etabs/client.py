"""Fixed API operations with strict return codes and complete call history."""
from __future__ import annotations

from contextlib import contextmanager
import json
import logging
from pathlib import Path
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)


def checked(result: Any, operation: str) -> tuple[Any, ...]:
    """comtypes returns in/out values followed by CSI's integer return code."""
    values = tuple(result) if isinstance(result, (tuple, list)) else (result,)
    if not values or type(values[-1]) is not int:
        raise TypeError(f'{operation}: missing integer API return code: {result!r}')
    if values[-1] != 0:
        raise RuntimeError(f'{operation}: ETABS return code {values[-1]}')
    return values[:-1]


class ETABSClient:
    def __init__(self, model: Any, log: Path) -> None:
        self.model = model
        self.log = log

    def call(self, operation: str, method: Callable[..., Any], *args: Any) -> tuple[Any, ...]:
        """Methods come only from adapter source, never from external requests."""
        try:
            result = method(*args)
            values = checked(result, operation)
        except Exception as error:
            with self.log.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'operation':operation, 'status':'ERROR',
                    'error_type':type(error).__name__, 'message':str(error)})+'\n')
            raise
        with self.log.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'operation':operation, 'status':'SUCCESS'})+'\n')
        return values


@contextmanager
def session(install_root: Path, directory: Path) -> Iterator[ETABSClient]:
    """Always create a dedicated application; never attach to a user session."""
    import comtypes.client
    api = comtypes.client.GetModule(str(install_root/'ETABSv1.tlb'))
    helper = comtypes.client.CreateObject('ETABSv1.Helper', interface=api.cHelper)
    app = helper.CreateObject(str(install_root/'ETABS.exe'))
    client = ETABSClient(app.SapModel, directory/'api_calls.jsonl')
    try:
        client.call('ApplicationStart', app.ApplicationStart)
        client.call('Hide', app.Hide)
        yield client
    finally:
        # Preserve original failures if the server has already crashed.
        try:
            client.call('ApplicationExit', app.ApplicationExit, False)
        except Exception:
            logger.exception('Failed to exit dedicated ETABS instance')


def rows(values: tuple[Any, ...], names: tuple[str, ...], *, operation: str) -> list[dict[str, Any]]:
    """Strict CSI results: NumberResults plus one array per named field."""
    if len(values) != len(names)+1 or type(values[0]) is not int or values[0] <= 0:
        raise ValueError(f'{operation}: missing/invalid result rows')
    count, arrays = values[0], values[1:]
    if any(not isinstance(a, (tuple, list)) or len(a) != count for a in arrays):
        raise ValueError(f'{operation}: inconsistent result array lengths')
    return [dict(zip(names, values)) for values in zip(*arrays)]
