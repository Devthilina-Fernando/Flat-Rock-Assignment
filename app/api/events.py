"""
GET /events — Server-Sent Events endpoint.
Streams real-time pipeline notifications to connected browser clients.

SSE wire format:
  data: <json>\n\n     — real event
  : keepalive\n\n      — comment, prevents proxy/browser timeouts
"""
import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

import app.services.event_bus as event_bus

router = APIRouter(tags=["events"])

_KEEPALIVE_SECONDS = 25  # below typical 30s proxy timeout


@router.get("/events")
async def sse_stream():
    sid, queue = event_bus.subscribe()

    async def generator():
        try:
            while True:
                try:
                    evt = await asyncio.wait_for(
                        queue.get(), timeout=_KEEPALIVE_SECONDS
                    )
                    yield f"data: {json.dumps(evt)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe(sid)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
