from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from . import config as cfg
from .models.PairRequest import PairRequest
from .sessions import SessionError

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

router = APIRouter()

class HTTPBearer403(HTTPBearer):
    def make_not_authenticated_error(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authenticated",
        )

CreditianlsDep = Annotated[HTTPAuthorizationCredentials, Depends(HTTPBearer403())]

class APIError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code

def websocket_path(role: str) -> dict[str, str]:
    return {
        channel: f"/ws/{channel}/{role}"
        for channel, roles in cfg.CHANNEL_ROLES.items()
        if role in roles
    }

async def read_limited(request: Request, limit: int) -> bytes:
    size = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise APIError(413, 'request_too_large')
        chunks.append(chunk)
    return b''.join(chunks)

@router.get('/healthz')
async def healthz() -> Response:
    return Response(status_code=204)

@router.post('/api/sessions', status_code=201)
async def create_session(request: Request) -> JSONResponse:
    manager = request.app.state.manager
    try:
        session, token = manager.create_session(time.time())
    except SessionError as e:
        raise APIError(e.status, e.message)

    expires = datetime.fromtimestamp(session.pairing_expires, tz=timezone.utc)
    return JSONResponse(status_code=201, content={
        "code": session.code,
        "browserToken": token,
        "expiresAt": expires.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "websocketPaths": websocket_path(cfg.ROLE_BROWSER),
    })

@router.post('/api/sessions/pair')
async def pair_session(request: Request) -> JSONResponse:
    host = request.client.host if request.client else 'unknown'
    if not request.app.state.pair_limiter.allow(host, time.time()):
        raise APIError(429, 'too_many_requests')

    body = await read_limited(request, cfg.MAX_PAIR_BODY)
    try:
        payload = PairRequest.model_validate_json(body)
    except ValidationError as e:
        raise APIError(400, f'invalid_request, {e}')

    try:
        _, token = request.app.state.manager.pair_session(payload.code, payload.role, time.time())
    except SessionError as e:
        raise APIError(e.status, e)

    return JSONResponse(content={
        "token": token,
        "websocketPaths": websocket_path(payload.role),
    })