from typing import Any, Awaitable, Callable, NamedTuple, Protocol
import asyncio


class KillRequest:
    pass


class ProccessRequest(NamedTuple):
    monotime: float
    response: asyncio.Queue[Exception | Any]


class FileProcessor(Protocol):
    async def __call__(self, file_uri: str) -> Awaitable: ...


class HandlerFailure(Exception):
    pass


async def handle_file(file_uri: str, monotime: float, file_processor: FileProcessor):
    worker_queue = _setup_worker(file_uri=file_uri, file_processor=file_processor)

    response_queue = asyncio.Queue(10)

    await worker_queue.put(ProccessRequest(monotime=monotime, response=response_queue))

    result = await response_queue.get()
    response_queue.task_done()

    if isinstance(result, Exception):
        raise result

    return result


async def shutdown_handlers():
    async with asyncio.TaskGroup() as task_group:
        for queue in _FILE_HANDLER_QUEUES.values():
            task_group.create_task(queue.put(KillRequest()))


def _setup_worker(
    file_uri: str, file_processor: FileProcessor
) -> asyncio.LifoQueue[ProccessRequest | KillRequest]:
    handler_key = f"{file_processor.__qualname__}${file_uri}"

    if handler_key in _FILE_HANDLER_QUEUES:
        return _FILE_HANDLER_QUEUES[handler_key]

    file_handler_queue = asyncio.LifoQueue[ProccessRequest | KillRequest]()
    _FILE_HANDLER_QUEUES[handler_key] = file_handler_queue

    handler_task = asyncio.create_task(
        _file_processor_handler(
            handler_key=handler_key, file_uri=file_uri, file_processor=file_processor
        ),
        name=handler_key,
    )
    _FILE_HANDLERS[handler_key] = handler_task

    handler_task.add_done_callback(_cleanup_file_handler)

    return file_handler_queue


_FILE_HANDLER_QUEUES: dict[str, asyncio.LifoQueue[ProccessRequest | KillRequest]] = {}
_FILE_HANDLERS: dict[str, asyncio.Task] = {}


def _cleanup_file_handler(file_handler: asyncio.Task):
    handler_key = file_handler.get_name()

    if handler_key in _FILE_HANDLERS:
        del _FILE_HANDLERS[handler_key]

    if handler_key in _FILE_HANDLER_QUEUES:
        queue = _FILE_HANDLER_QUEUES[handler_key]
        del _FILE_HANDLER_QUEUES[handler_key]

        err = HandlerFailure(f"Exception within handler for '{handler_key}'")

        # Unblock any processes waiting for this defunct handler.
        while not queue.empty():
            request = queue.get_nowait()
            try:
                match request:
                    case KillRequest():
                        continue
                    case ProccessRequest(response=response_queue):
                        response_queue.put_nowait(err)
            finally:
                queue.task_done()


async def _file_processor_handler(
    handler_key: str, file_uri: str, file_processor: Callable[[str, float], Awaitable]
):
    if handler_key not in _FILE_HANDLER_QUEUES:
        raise RuntimeError(
            f"{file_processor.__qualname__} for ('{file_uri}') not initialized."
        )

    handler_queue = _FILE_HANDLER_QUEUES[handler_key]

    last_monotime = 0
    last_result = None
    while True:
        work_request = await handler_queue.get()
        try:
            match work_request:
                case KillRequest():
                    break
                case ProccessRequest(
                    monotime=monotime, response=response_queue
                ) if monotime <= last_monotime:
                    await response_queue.put(last_result)
                    continue

                case ProccessRequest(monotime=monotime, response=response_queue):
                    try:
                        result = await file_processor(file_uri)
                        await response_queue.put(result)

                        last_monotime = monotime
                        last_result = result
                    except Exception as err:
                        await response_queue.put(err)
        finally:
            handler_queue.task_done()
