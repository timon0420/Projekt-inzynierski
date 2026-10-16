import uvicorn

from app import config as cfg

if __name__ == '__main__':
    uvicorn.run(
        "app.main:app",
        port=cfg.Settings.from_env().port,
        ws_ping_interval=cfg.PING_INTERVAL,
        ws_ping_timeout=cfg.PONG_WAIT - cfg.PING_INTERVAL,
        ws_max_size=cfg.MAX_MESSAGE_SIZE,
        workers=1,
    )