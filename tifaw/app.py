"""Tifaw — Native macOS app launcher using pywebview."""
from __future__ import annotations

import logging
import socket
import threading
import time

import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 8321


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, port)) == 0


def _start_server():
    uvicorn.run(
        "tifaw.main:app",
        host=HOST,
        port=PORT,
        log_level="warning",
    )


def _wait_for_server(timeout: int = 15):
    start = time.time()
    while time.time() - start < timeout:
        if _port_in_use(PORT):
            return True
        time.sleep(0.2)
    return False


def main():
    import webview

    # Start server in background unless it's already running
    if not _port_in_use(PORT):
        server = threading.Thread(target=_start_server, daemon=True)
        server.start()
        logger.info("Starting Tifaw server...")

        if not _wait_for_server():
            logger.error("Server failed to start within timeout")
            return
    else:
        logger.info("Server already running on port %d", PORT)

    logger.info("Opening Tifaw window...")
    webview.create_window(
        "Tifaw",
        f"http://{HOST}:{PORT}",
        width=1200,
        height=800,
        min_size=(800, 500),
    )
    webview.start()


if __name__ == "__main__":
    main()
