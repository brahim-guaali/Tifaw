"""Tifaw — Native macOS menubar app launcher.

Runs Tifaw as an LSUIElement (agent) app: only a menubar icon
is shown, with the main window opened on demand. Indexing
continues in the background regardless of whether the window
is open.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
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


def _wait_for_server(timeout: int = 15) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if _port_in_use(PORT):
            return True
        time.sleep(0.2)
    return False


def _get_resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(
            getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)),
        )
    return Path(__file__).parent.parent


def _set_macos_branding():
    """Set the About-panel fields. Dock icon is NOT set because
    we run as an accessory app (no dock presence)."""
    try:
        from Foundation import NSBundle

        bundle = NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info:
            info["CFBundleName"] = "Tifaw"
            info["CFBundleDisplayName"] = "Tifaw"
            info["CFBundleShortVersionString"] = "0.2.1"
            info["CFBundleVersion"] = "0.2.1"
            info["NSHumanReadableCopyright"] = (
                "Tifaw — Your laptop's story, powered by local AI."
            )
    except Exception as e:
        logger.debug("Failed to set macOS branding: %s", e)


def _lower_priority():
    """Run indexing/server with a lower scheduling priority so
    the user's foreground work isn't impacted."""
    try:
        os.nice(10)
    except (AttributeError, PermissionError):
        pass


def main():
    _lower_priority()
    _set_macos_branding()

    # Start the FastAPI server in a background thread
    if not _port_in_use(PORT):
        server = threading.Thread(target=_start_server, daemon=True)
        server.start()
        logger.info("Starting Tifaw server...")
        if not _wait_for_server():
            logger.error("Server failed to start within timeout")
            return
    else:
        logger.info("Server already running on port %d", PORT)

    # Import pywebview + AppKit only after server is up
    import webview
    from AppKit import (
        NSApplication,
        NSApplicationActivationPolicyAccessory,
    )

    # Become an "accessory" app — no dock icon, menubar only
    ns_app = NSApplication.sharedApplication()
    ns_app.setActivationPolicy_(
        NSApplicationActivationPolicyAccessory,
    )

    # Lazy window reference — created on first "Open Tifaw"
    window_ref: dict = {"w": None}

    def open_window() -> None:
        # Bring the (pre-created, hidden) window forward
        w = window_ref["w"]
        if w is not None:
            try:
                w.show()
            except Exception:
                logger.exception("Failed to show window")
        # Activate the app so the window gets focus above others
        try:
            from AppKit import (
                NSApplicationActivationPolicyRegular,
            )

            ns_app.setActivationPolicy_(
                NSApplicationActivationPolicyRegular,
            )
            ns_app.activateIgnoringOtherApps_(True)
        except Exception:
            pass

    # Menubar must be created before webview.start()
    from tifaw.menubar import TifawMenubar

    menubar = TifawMenubar.alloc().init()
    menubar.set_window_opener(open_window)

    # Create initial hidden window so webview.start() has something
    # to run; hide it immediately so the app starts silent.
    initial = webview.create_window(
        "Tifaw",
        f"http://{HOST}:{PORT}",
        width=1200,
        height=800,
        min_size=(800, 500),
        hidden=True,
    )
    window_ref["w"] = initial

    logger.info("Tifaw running in menubar")
    # webview.start() runs the Cocoa main loop; the menubar lives
    # inside the same NSApplication, so both work together.
    webview.start(gui="cocoa", debug=False)


if __name__ == "__main__":
    main()
