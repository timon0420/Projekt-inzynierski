from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass, field
from fastapi import WebSocket
from . import config as cfg

class SessionError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status

@dataclass(frozen=True, slots=True)
class Outbound:
    payload: bytes | str

class Client:
    def __init__(self, websocket: WebSocket, maxsize: int):
        self.websocket = websocket
        self.queue: asyncio.Queue[Outbound] = asyncio.Queue(maxsize=maxsize)
        self._writer: asyncio.Task | None = None

    def start(self) -> None:
        self._writer = asyncio.create_task(self._write_pump())

    async def _write_pump(self) -> None:
        try:
            while True:
                message = await self.queue.get()
                if isinstance(message.payload, bytes):
                    send = self.websocket.send_bytes(message.payload)
                else:
                    send = self.websocket.send_text(message.payload)
                await asyncio.wait_for(send, cfg.WRITE_WAIT)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._close_socket()

    async def _close_socket(self, code: int = 1000) -> None:
        try:
            await self.websocket.close(code=code)
        except Exception:
            pass

    async def close(self, code: int = 1000) -> None:
        current = asyncio.current_task()
        if self._writer and self._writer is not current and not self._writer.done():
            self._writer.cancel()
        await self._close_socket(code)

@dataclass(eq=False)
class Session:
    id: str
    code: str
    created_at: float
    pairing_expires: float
    last_action: float
    tokens: dict[str, str] = field(default_factory=dict)
    paired: set[str] = field(default_factory=set)
    clients: dict[tuple[str, str], Client] = field(default_factory=dict)
    source: str = ''
    last_sequence: int = 0

def normalize_code(code: str) -> str:
    clean = code.strip().replace('-', '').replace(' ', '').upper()
    if len(clean) == 8:
        return f'{clean[:4]}-{clean[4:]}'
    return clean

def random_token(size: int) -> str:
    return secrets.token_urlsafe(size)

class SessionManager:
    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self.tokens: dict[str, Session] = {}
        self.codes: dict[str, Session] = {}

    def create_session(self, now: float) -> tuple[Session, str]:
        if len(self.sessions) >= cfg.MAX_SESSIONS:
            raise SessionError('Maximum number of sessions reached', 503)

        code = self._unique_code()
        browser_token = random_token(32)
        session = Session(
            id=random_token(18),
            code=code,
            created_at=now,
            pairing_expires=now + cfg.PAIRING_TTL,
            last_action=now,
            tokens={cfg.ROLE_BROWSER: browser_token},
            paired={cfg.ROLE_BROWSER},
        )
        self.sessions[session.id] = session
        self.codes[code] = session
        self.tokens[browser_token] = session
        return session, browser_token

    def pair_session(self, code: str, role: str, now: float) -> tuple[Session, str]:
        if role not in cfg.PAIRABLE_ROLES:
            raise SessionError(f'Role {role} cannot pair', 400)

        session = self.codes.get(normalize_code(code))
        if session is None or now > session.pairing_expires:
            raise SessionError('Invalid or expired pairing code', 400)
        if role in session.paired:
            raise SessionError(f'Role {role} already paired', 400)

        token = random_token(32)
        session.paired.add(role)
        session.tokens[role] = token
        session.last_action = now
        self.tokens[token] = session
        return session, token

    def session_for_token(self, token: str, role: str) -> Session | None:
        session = self.tokens.get(token)
        if session is None or session.tokens.get(role) != token:
            return None
        return session

    def _unique_code(self) -> str:
        for _ in range(100):
            raw = ''.join(secrets.choice(cfg.CODE_ALPHABET) for _ in range(8))
            code = f'{raw[:4]}-{raw[4:]}'
            if code not in self.codes:
                return code
        raise SessionError('Failed to generate unique code', 503)

    def register_client(self, session: Session, channel: str, role: str, client: Client, now: float) -> Client | None:
        previous = session.clients.get((channel, role))
        session.clients[(channel, role)] = client
        session.last_action = now
        return previous

    def unregister_client(self, session: Session, channel: str, role: str, client: Client, now: float) -> None:
        if session.clients.get((channel, role)) is client:
            del session.clients[(channel, role)]
            session.last_action = now

    def route(self, session: Session, channel: str, role: str, message: Outbound, latest: bool) -> None:
        target = session.clients.get((channel, role))
        if target is None:
            return False
        queue = target.queue
        if latest:
            try:
                queue.get_nowait(message)
                return True
            except asyncio.QueueFull:
                pass
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(message)
            return True
        except asyncio.QueueFull:
            return False

    def status(self, session: Session) -> str:
        py_video = (cfg.CHANNEL_VIDEO, cfg.ROLE_PYTHON) in session.clients
        py_angles = (cfg.CHANNEL_ANGLES, cfg.ROLE_PYTHON) in session.clients
        return json.dumps({
            "type": "status",
            "python": py_video or py_angles,
            "pythonVideo": py_video,
            "pythonAngles": py_angles,
            "unity": (cfg.CHANNEL_ANGLES, cfg.ROLE_UNITY) in session.clients,
            "source": session.source,
        })

    def set_source(self, session: Session, source: str, now: float) -> None:
        session.source = source
        session.last_action = now

    def accept_sequence(self, session: Session, sequence: int, now: float) -> bool:
        if sequence <= session.last_sequence:
            return False
        session.last_sequence = sequence
        session.last_action = now
        return True

    def cleanup(self, now: float) -> None:
        to_close: list[Client] = []
        for session_id, session in list(self.sessions.items()):
            no_clients = not session.clients
            alive = (now - session.created_at < cfg.MAX_SESSION_AGE and (not no_clients or now - session.last_action < cfg.DISCONNECT_TTL))
            if alive:
                continue
            for token in session.tokens.values():
                self.tokens.pop(token, None)
            self.codes.pop(session.code, None)
            del self.sessions[session_id]
            to_close.extend(session.clients.values())
            session.clients.clear()
        return to_close

class PairRateLimiter:
    def __init__(self, limit: int = cfg.MAX_PAIRING_PER_MINUTE):
        self.limit = limit
        self._entries: dict[str, tuple[float, int]] = {}

    def allow(self, host: str, now: float) -> bool:
        window, count = self._entries.get(host, (0.0, 0))
        if now - window >= 60:
            window, count = now, 0
        count += 1
        self._entries[host] = (window, count)
        return count <= self.limit

    def prune(self, now: float) -> None:
        for host, (window, _) in list(self._entries.items()):
            if now - window >= 60:
                del self._entries[host]
