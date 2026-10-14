from __future__ import annotations

import asyncio
import json
import time
from fastapi import APIRouter, Query, WebSocket
from fastapi.websockets import WebSocketDisconnect
from pydantic import ValidationError

from . import config as cfg
from .models.GestureData import GestureData
from .models.PairRequest import PairRequest
from .models.SourceMessage import SourceMessage
from .sessions import Client, Outbound, Session, SessionManager

router = APIRouter()

def is_jpeg(data: bytes) -> bool:
    return (len(data) >= 4 and data[0] == 0xFF and data[1] == 0xD8 and data[-2] == 0xFF and data[-1] == 0xD9)

def origin_allowed(websocket: WebSocket) -> bool:
    allowed = websocket.app.state.settings.allowed_origins
    origin = websocket.headers.get('origin')
    return not allowed or not origin or origin in allowed

def send_status(manager: SessionManager, session: Session) -> None:
    manager.route(session, cfg.CHANNEL_ANGLES, cfg.ROLE_BROWSER, Outbound(manager.status(session)), latest=True)

def handle_python_message(manager: SessionManager, session: Session, text: str) -> None:
    try:
        envelope = json.loads(text)
    except ValueError:
        return
    if not isinstance(envelope, dict):
        return

    kind = envelope.get('type')
    now = time.time()

    if kind == 'source':
        try:
            msg = SourceMessage.model_validate(envelope)
        except ValidationError:
            return
        manager.set_source(session, msg.source, now)
        manager.route(session, cfg.CHANNEL_ANGLES, cfg.ROLE_BROWSER, Outbound(manager.status(session)), latest=False)
    elif kind == 'angles':
        try:
            gesture = GestureData.model_validate(envelope)
        except ValidationError:
            return
        if not manager.accept_sequence(session, gesture.sequence, now):
            return
        manager.route(session, cfg.CHANNEL_ANGLES, cfg.ROLE_UNITY, Outbound(gesture.model_dump_json()), latest=True)

async def read_loop(websocket: WebSocket, manager: SessionManager, session: Session, channel: str, role: str) -> None:
    last_frame = float('-inf')
    while True:
        message = await websocket.receive()
        if message['type'] == 'websocket.disconnect':
            return
        data: bytes | None = message.get('bytes')
        text: str | None = message.get('text')

        if channel == cfg.CHANNEL_VIDEO and role == cfg.ROLE_BROWSER:
            if (data is None or len(data) > cfg.MAX_JPEG_SIZE or not is_jpeg(data)):
                continue
            now = time.monotonic()
            if now - last_frame < cfg.MIN_FRAME_INTERVAL:
                continue
            last_frame = now
            manager.route(session, cfg.CHANNEL_VIDEO, cfg.ROLE_PYTHON, Outbound(data), latest=True)
        elif channel == cfg.CHANNEL_ANGLES and role == cfg.ROLE_PYTHON:
            if text is not None:
                handle_python_message(manager, session, text)

async def serve(websocket: WebSocket, channel: str, role: str, token: str) -> None:
    manager: SessionManager = websocket.app.state.manager
    session = manager.session_for_token(token, role)

    if session is None or not origin_allowed(websocket):
        await websocket.close(code=1008)
        return

    await websocket.accept()

    client = Client(websocket, cfg.queue_size(channel, role))
    previous = manager.register_client(session, channel, role, client, time.time())
    if previous is not None:
        await previous.close(1000)
    client.start()
    send_status(manager, session)

    try:
        await read_loop(websocket, manager, session, channel, role)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        manager.unregister_client(session, channel, role, client, time.time())
        await client.close()
        send_status(manager, session)

def _make_handler(channel: str, role: str):
    async def handler(websocket: WebSocket, token: str = Query('')) -> None:
        await serve(websocket, channel, role, token)
    return handler

for _channel, _roles in cfg.CHANNEL_ROLES.items():
    for _role in _roles:
        router.add_api_websocket_route(f'/ws/{_channel}/{_role}', _make_handler(_channel, _role))
