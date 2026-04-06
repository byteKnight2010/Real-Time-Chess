"""ChessNetwork — thin TCP transport layer for LAN multiplayer.

Host is the authoritative game server (plays White).
Client connects to the host (plays Black).

Wire protocol  (newline-terminated UTF-8 lines):
    MOVE:fc,fr,tc,tr,promo     client → host  (promo may be empty string)
    STATE:<json>               host  → client  (full board snapshot every move)
    GAME_OVER:<reason>         host  → client  (redundant; also embedded in STATE)

All network I/O runs in background threads.  The game loop calls
drainIncoming() every frame to collect queued messages without blocking.
"""

import json
import logging
import queue
import socket
import threading
from typing import Callable, Optional

log: logging.Logger = logging.getLogger("chess")

PORT: int = 55_765          # default LAN port (not well-known, unlikely to conflict)
RECV_BUF: int = 16_384


class ChessNetwork:
    """Non-blocking wrapper around a connected TCP socket.

    Create via the class-methods ``listen()`` (host) or ``join()`` (client).
    Both block the calling thread until the connection is established, so
    always call them from a worker thread, not the main game loop.
    """

    def __init__(self, sock: socket.socket, is_host: bool) -> None:
        self._sock: socket.socket = sock
        self._sock.settimeout(1.0)          # allows reader thread to check _closed
        self.isHost: bool = is_host
        self._in: queue.Queue = queue.Queue()
        self._out: queue.Queue = queue.Queue()
        self._closed: threading.Event = threading.Event()

        self._reader: threading.Thread = threading.Thread(
            target=self._readLoop, daemon=True, name="LAN-Read"
        )
        self._writer: threading.Thread = threading.Thread(
            target=self._writeLoop, daemon=True, name="LAN-Write"
        )
        self._reader.start()
        self._writer.start()

    # ── factories ──────────────────────────────────────────────────────────

    @classmethod
    def listen(
        cls,
        port: int = PORT,
        on_status: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> "ChessNetwork":
        """Open a server socket and block until one client connects.

        Parameters
        ----------
        on_status:
            Optional callable invoked with ``"waiting"`` once the socket is
            bound and then ``"connected"`` when the client arrives.
        stop_event:
            When set, the listen loop exits with a ``ConnectionAbortedError``.
        """
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("", port))
        srv.listen(1)
        srv.settimeout(1.0)
        log.info(f"LAN host: listening on :{port}")
        if on_status:
            on_status("waiting")
        try:
            while True:
                if stop_event and stop_event.is_set():
                    raise ConnectionAbortedError("Cancelled by user")
                try:
                    conn, addr = srv.accept()
                    break
                except socket.timeout:
                    continue
        finally:
            srv.close()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        log.info(f"LAN host: client connected from {addr}")
        if on_status:
            on_status("connected")
        return cls(conn, is_host=True)

    @classmethod
    def join(
        cls,
        ip: str,
        port: int = PORT,
        timeout: float = 10.0,
    ) -> "ChessNetwork":
        """Connect to a host.  Raises on failure."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        log.info(f"LAN client: connected to {ip}:{port}")
        return cls(sock, is_host=False)

    # ── background I/O threads ─────────────────────────────────────────────

    def _readLoop(self) -> None:
        buf = b""
        try:
            while not self._closed.is_set():
                try:
                    chunk = self._sock.recv(RECV_BUF)
                except socket.timeout:
                    continue
                if not chunk:
                    log.info("LAN: peer closed connection")
                    self._in.put(("DISCONNECT", None))
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._dispatch(line.decode("utf-8", errors="replace").strip())
        except Exception:
            log.exception("LAN reader error")
            self._in.put(("DISCONNECT", None))

    def _dispatch(self, msg: str) -> None:
        if not msg:
            return
        if msg.startswith("MOVE:"):
            try:
                parts = msg[5:].split(",")
                fc, fr, tc, tr = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                promo = parts[4].strip() if len(parts) > 4 else ""
                self._in.put(("MOVE", (fc, fr, tc, tr, promo)))
            except Exception:
                log.warning(f"LAN: malformed MOVE: {msg!r}")
        elif msg.startswith("STATE:"):
            try:
                self._in.put(("STATE", json.loads(msg[6:])))
            except Exception:
                log.warning("LAN: malformed STATE JSON")
        elif msg.startswith("GAME_OVER:"):
            self._in.put(("GAME_OVER", msg[10:].strip()))
        else:
            log.debug(f"LAN: unknown msg: {msg!r}")

    def _writeLoop(self) -> None:
        try:
            while not self._closed.is_set():
                try:
                    data: str = self._out.get(timeout=0.2)
                    self._sock.sendall(data.encode("utf-8"))
                except queue.Empty:
                    continue
        except Exception:
            log.exception("LAN writer error")

    # ── public send API ────────────────────────────────────────────────────

    def sendMove(self, fc: int, fr: int, tc: int, tr: int, promo: str = "") -> None:
        """Client → Host: move intention (with optional promotion type)."""
        self._out.put(f"MOVE:{fc},{fr},{tc},{tr},{promo}\n")

    def sendState(self, json_str: str) -> None:
        """Host → Client: full authoritative board snapshot."""
        self._out.put(f"STATE:{json_str}\n")

    def sendGameOver(self, reason: str) -> None:
        self._out.put(f"GAME_OVER:{reason}\n")

    # ── public receive API ─────────────────────────────────────────────────

    def drainIncoming(self) -> list:
        """Return all queued messages as a list of (kind, data) tuples.

        Kinds: ``"MOVE"``, ``"STATE"``, ``"GAME_OVER"``, ``"DISCONNECT"``.
        Call once per frame from the game loop.
        """
        msgs = []
        while True:
            try:
                msgs.append(self._in.get_nowait())
            except queue.Empty:
                break
        return msgs

    # ── lifecycle ──────────────────────────────────────────────────────────

    def close(self) -> None:
        """Signal threads to stop and close the socket."""
        self._closed.set()
        try:
            self._sock.close()
        except Exception:
            pass

    @property
    def alive(self) -> bool:
        return not self._closed.is_set()


# ── convenience helper ─────────────────────────────────────────────────────

def get_local_ip() -> str:
    """Best-effort local LAN IP (not 127.0.0.1)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"