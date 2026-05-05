"""
In-process event bus: bridges sync background threads → async SSE subscribers.

The event loop is stored once at startup (set_loop). publish() is then callable
from any sync thread without needing to pass the loop each time.
"""
import asyncio
import threading

_subscribers: dict[int, asyncio.Queue] = {}
_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Call once from the FastAPI lifespan after the event loop is running."""
    global _loop
    _loop = loop


def subscribe() -> tuple[int, asyncio.Queue]:
    """Register a new SSE subscriber. Returns (subscriber_id, queue)."""
    q: asyncio.Queue = asyncio.Queue()
    sid = id(q)
    with _lock:
        _subscribers[sid] = q
    return sid, q


def unsubscribe(sid: int) -> None:
    """Remove a subscriber when its SSE connection closes."""
    with _lock:
        _subscribers.pop(sid, None)


def publish(event: dict) -> None:
    """
    Broadcast an event to all subscribers. Safe to call from any thread.
    No-ops silently if no loop is set or no subscribers are connected.
    """
    if _loop is None:
        return
    with _lock:
        current = list(_subscribers.values())
    for q in current:
        _loop.call_soon_threadsafe(q.put_nowait, event)


def subscriber_count() -> int:
    with _lock:
        return len(_subscribers)
