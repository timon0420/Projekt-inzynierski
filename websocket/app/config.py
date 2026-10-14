from __future__ import annotations

import os
from dataclasses import dataclass

ROLE_BROWSER = 'browser'
ROLE_PYTHON = 'python'
ROLE_UNITY = 'unity'

PAIRABLE_ROLES = (ROLE_PYTHON, ROLE_UNITY)

CHANNEL_VIDEO = 'video'
CHANNEL_ANGLES = 'angles'

CHANNEL_ROLES: dict[str, tuple[str, ...]] = {
    CHANNEL_VIDEO: (ROLE_BROWSER, ROLE_PYTHON),
    CHANNEL_ANGLES: (ROLE_BROWSER, ROLE_PYTHON, ROLE_UNITY),
}

MAX_JPEG_SIZE = 200 * 1024  # 200 KB
MAX_MESSAGE_SIZE = MAX_JPEG_SIZE + 1024  # 200 KB + 1 KB for metadata
MAX_SESSIONS = 100
MAX_PAIR_BODY = 4096
PAIRING_TTL = 15 * 60  # 15 minutes
MAX_SESSION_AGE = 4 * 60 * 60  # 4 hours
DISCONNECT_TTL = 5 * 60  # 5 minutes
WRITE_WAIT = 5.0
PING_INTERVAL = 25.0
PONG_WAIT = 70.0
MIN_FRAME_INTERVAL = 0.033  # 30 FPS
MAX_PAIRING_PER_MINUTE = 10
CLEANUP_INTERVAL = 60.0  # 1 minute

CODE_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'

def queue_size(channel: str, role: str) -> int:
    if channel == CHANNEL_VIDEO and role == ROLE_PYTHON:
        return 1
    return 8

@dataclass(frozen=True)
class Settings:
    allowed_origins: tuple[str, ...] = ()
    port: int = 8080

    @classmethod
    def from_env(cls) -> "Settings":
        raw = os.getenv('ALLOWED_ORIGINS', '')
        origins = tuple(o.strip() for o in raw.split(',') if o.strip())
        return cls(allowed_origins=origins, port=int(os.getenv('PORT', 8080)))
