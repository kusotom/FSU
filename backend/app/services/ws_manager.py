import json
from collections import defaultdict

from fastapi import WebSocket


class WSConnectionManager:
    def __init__(self):
        self._by_channel: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, channel: str):
        await websocket.accept()
        self._by_channel[channel].add(websocket)

    def disconnect(self, websocket: WebSocket, channel: str):
        if channel in self._by_channel:
            self._by_channel[channel].discard(websocket)

    async def broadcast(self, channel: str, payload: dict):
        dead = []
        message = json.dumps(payload, default=str)
        for ws in self._by_channel.get(channel, set()):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._by_channel[channel].discard(ws)


ws_manager = WSConnectionManager()

