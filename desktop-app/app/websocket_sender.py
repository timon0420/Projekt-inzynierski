from __future__ import annotations
import asyncio, json, os, queue, threading, time
from urllib.parse import urlparse, urlencode, urlunparse
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from websockets.asyncio.client import connect

class SessionWebSocketClient:
    def __init__(self, api_url: str | None = None):
        self.api_url = (api_url or os.environ.get("WEBSOCKET_API_URL", "https://projekt-inzynierski-3qav.onrender.com")).rstrip("/")
        self.connected = False
        self.last_error: str | None = None
        self._token: str | None = None
        self.session_code: str | None = None
        self._websocket_path = "/ws/python"
        self._code: str | None = None
        self._source = "local_camera"
        self._sequence = 0
        self._outbound: queue.Queue[str] = queue.Queue(maxsize=1)
        self._frames: queue.Queue[bytes] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, code: str, source: str):
        if source not in {"local_camera", "remote_camera"}:
            raise ValueError(f"Invalid source: {source}")
        if self._thread and self._thread.is_alive():
            self.set_source(source)
            return
        self._code = code.strip()
        self._token = None
        if not self._code and source == "remote_camera":
            raise ValueError("Code is required for remote_camera source.")
        self._source = source
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._thread_main, name="session-websocket", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.3)
        self._thread = None
        self.connected = False

    def set_source(self, source: str):
        if source not in {"local_camera", "remote_camera"}:
            raise ValueError(f"Invalid source: {source}")
        self._source = source
        self._put_latest(json.dumps({"type": "source", "source": source}))

    def send_angles(self, angles: list[float] | tuple[float, ...]):
        if len(angles) != 6:
            raise ValueError(f"Expected 6 angles, got {len(angles)}")
        values = [float(angle) for angle in angles]
        if not all(0.0 <= angle <= 1.0 for angle in values):
            raise ValueError(f"Angles must be in range [0.0, 1.0], got {values}")
        self._sequence += 1
        self._put_latest(json.dumps({
            "type": "angles",
            "angles": values,
            "timestamp": time.time(),
            "sequence": self._sequence,
        }, separators=(",", ":")))

    def get_latest_frame(self):
        latest = None
        while True:
            try:
                latest = self._frames.get_nowait()
            except queue.Empty:
                return latest

    def _put_latest(self, message: str):
        try:
            self._outbound.put_nowait(message)
        except queue.Full:
            try:
                self._outbound.get_nowait()
            except queue.Empty:
                pass
            self._outbound.put_nowait(message)

    def _put_latest_frame(self, frame: bytes):
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                pass
            self._frames.put_nowait(frame)

    def _thread_main(self):
        try:
            asyncio.run(self._run())
        except Exception as e:
            self.last_error = str(e)
            self.connected = False
            print("WEBSOCKET ERROR: ", e)

    async def _run(self):
        delay = 1.0
        while not self._stop_event.is_set():
            try:
                if not self._token:
                    if not self._code:
                        await asyncio.to_thread(self._create_session)
                    await asyncio.to_thread(self._pair)
                async with connect(
                    self._websocket_url(),
                    ping_interval=25,
                    ping_timeout=20,
                    max_size=256 * 1024,
                    open_timeout=10,
                ) as websocket:
                    self.connected = True
                    self.last_error = None
                    delay = 1.0
                    await websocket.send(json.dumps({"type": "source", "source": self._source}))
                    receiver = asyncio.create_task(self._receive_loop(websocket))
                    sender = asyncio.create_task(self._send_loop(websocket))
                    done, pending = await asyncio.wait(
                        [receiver, sender],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                    for task in done:
                        task.result()
            except (OSError, HTTPError, URLError, ValueError, ConnectionError) as e:
                self.last_error = str(e)
                print("WEBSOCKET ERROR: ", e)
            except Exception as e:
                self.last_error = f"Unexpected error: {e}"
                print("WEBSOCKET ERROR: ", e)
            finally:
                self.connected = False
            if not self._stop_event.is_set():
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)

    async def _receive_loop(self, websocket):
        async for message in websocket:
            if isinstance(message, bytes):
                self._put_latest_frame(message)

    async def _send_loop(self, websocket):
        while not self._stop_event.is_set():
            try:
                message = await asyncio.to_thread(self._outbound.get, True, 0.2)
            except queue.Empty:
                continue
            await websocket.send(message)

    def _pair(self) -> None:
        payload = json.dumps({"code": self._code, "role": "python"}).encode("utf-8")
        request = Request(
            f"{self.api_url}/api/sessions/pair",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                result = json.load(response)
        except HTTPError as error:
            try:
                detail = json.load(error).get("error", str(error))
            except Exception:
                detail = str(error)
            raise ConnectionError(f"Parowanie nie powiodło się: {detail}") from error
        self._token = result["token"]
        self._websocket_path = result.get("websocketPath", "/ws/python")

    def _create_session(self) -> None:
        request = Request(f"{self.api_url}/api/sessions", data=b"", method="POST")
        try:
            with urlopen(request, timeout=10) as response:
                result = json.load(response)
        except HTTPError as error:
            try:
                detail = json.load(error).get("error", str(error))
            except Exception:
                detail = str(error)
            raise ConnectionError(f"Nie udało się utworzyć sesji: {detail}") from error
        self._code = result["code"]
        self.session_code = self._code

    def _websocket_url(self) -> str:
        if not self._token:
            raise ConnectionError("Brak tokenu sesji.")
        parsed = urlparse(self.api_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunparse((
            scheme,
            parsed.netloc,
            self._websocket_path,
            "",
            urlencode({"token": self._token}),
            "",
        ))
