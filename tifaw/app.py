"""Tifaw — Native macOS app launcher using pywebview."""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

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


def _get_resource_dir() -> Path:
    """Return the resource directory, handling both dev and frozen .app bundle."""
    if getattr(sys, "frozen", False):
        # PyInstaller extracts data to sys._MEIPASS
        return Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return Path(__file__).parent.parent


def _set_macos_branding():
    """Set the macOS dock icon, app name, and About panel."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle

        app = NSApplication.sharedApplication()

        # Set dock icon and About panel icon
        icon_path = _get_resource_dir() / "frontend" / "icon.png"
        if icon_path.exists():
            icon = NSImage.alloc().initWithContentsOfFile_(str(icon_path))
            if icon:
                app.setApplicationIconImage_(icon)

        # Override bundle info for About panel and menu bar
        bundle = NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info:
            info["CFBundleName"] = "Tifaw"
            info["CFBundleDisplayName"] = "Tifaw"
            info["CFBundleShortVersionString"] = "0.1.0"
            info["CFBundleVersion"] = "0.1.0"
            info["NSHumanReadableCopyright"] = "Tifaw — Your laptop's story, powered by local AI."

        logger.info("macOS branding set (icon + app name)")
    except ImportError:
        logger.debug("AppKit not available, skipping macOS branding")
    except Exception as e:
        logger.debug("Failed to set macOS branding: %s", e)


def main():
    # Set app name BEFORE any AppKit/webview initialization
    try:
        from Foundation import NSBundle, NSProcessInfo
        # Set bundle name (affects menu bar)
        bundle = NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info:
            info["CFBundleName"] = "Tifaw"
            info["CFBundleDisplayName"] = "Tifaw"
        # Set process name (affects dock tooltip)
        NSProcessInfo.processInfo().setProcessName_("Tifaw")
    except Exception:
        pass

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

    # Set custom dock icon
    _set_macos_branding()

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
