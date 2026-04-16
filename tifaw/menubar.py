"""macOS menubar (status bar) UI for Tifaw.

Presents a native NSStatusItem with an NSPopover containing a
WKWebView that loads a rich HTML UI from the local Tifaw server
(``/menubar.html``). Communication from the web UI back to the
native shell uses a WKScriptMessageHandler (``window.tifaw``).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import objc
from AppKit import (
    NSApp,
    NSImage,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import (
    NSURL,
    NSMakeRect,
    NSObject,
    NSURLRequest,
)
from WebKit import (
    WKUserContentController,
    WKWebView,
    WKWebViewConfiguration,
)

_WKScriptMessageHandler = objc.protocolNamed("WKScriptMessageHandler")

logger = logging.getLogger(__name__)

MENUBAR_URL = "http://127.0.0.1:8321/menubar.html"
POPOVER_WIDTH = 340
POPOVER_HEIGHT = 400


def _resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(
            getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)),
        )
    return Path(__file__).parent.parent


class _ScriptHandler(NSObject, protocols=[_WKScriptMessageHandler]):
    """Bridge class for WKScriptMessageHandler callbacks."""

    def initWithCallback_(self, callback):  # noqa: N802
        self = objc.super(_ScriptHandler, self).init()
        if self is None:
            return None
        self._callback = callback
        return self

    def userContentController_didReceiveScriptMessage_(  # noqa: N802
        self, _controller, message,
    ):
        try:
            self._callback(message.body())
        except Exception:
            logger.exception("Script message callback failed")


class TifawMenubar(NSObject):
    """Menubar controller. Instantiate via ``alloc().init()``."""

    def init(self):  # noqa: N802
        self = objc.super(TifawMenubar, self).init()
        if self is None:
            return None
        self._window_opener = None
        self._quit_handler = None
        self._popover = None
        self._webview = None
        self._build_status_item()
        return self

    def set_window_opener(self, fn):
        self._window_opener = fn

    def set_quit_handler(self, fn):
        self._quit_handler = fn

    # ---- Status bar icon ----

    def _build_status_item(self) -> None:
        bar = NSStatusBar.systemStatusBar()
        self.item = bar.statusItemWithLength_(
            NSVariableStatusItemLength,
        )

        icon_path = _resource_dir() / "frontend" / "icon.png"
        if icon_path.exists():
            icon = NSImage.alloc().initWithContentsOfFile_(
                str(icon_path),
            )
            if icon is not None:
                from AppKit import NSSize

                icon.setSize_(NSSize(20, 20))
                self.item.button().setImage_(icon)
        else:
            self.item.button().setTitle_("T")

        self.item.button().setTarget_(self)
        self.item.button().setAction_("togglePopover:")

    # ---- Popover (WKWebView) ----

    def _ensure_popover(self) -> None:
        if self._popover is not None:
            return

        from AppKit import (
            NSPopover,
            NSPopoverBehaviorTransient,
        )

        config = WKWebViewConfiguration.alloc().init()
        controller = WKUserContentController.alloc().init()
        self._script_handler = (
            _ScriptHandler.alloc().initWithCallback_(self._on_message)
        )
        controller.addScriptMessageHandler_name_(
            self._script_handler, "tifaw",
        )
        config.setUserContentController_(controller)

        webview = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, POPOVER_WIDTH, POPOVER_HEIGHT),
            config,
        )
        # Inject a JS bridge so the web UI can call `tifaw.openWindow()`
        bridge_js = """
            window.tifaw = {
                openWindow: function() {
                    window.webkit.messageHandlers.tifaw.postMessage(
                        {action: 'openWindow'}
                    );
                },
                quit: function() {
                    window.webkit.messageHandlers.tifaw.postMessage(
                        {action: 'quit'}
                    );
                }
            };
        """
        from WebKit import (
            WKUserScript,
            WKUserScriptInjectionTimeAtDocumentStart,
        )

        user_script = (
            WKUserScript.alloc()
            .initWithSource_injectionTime_forMainFrameOnly_(
                bridge_js,
                WKUserScriptInjectionTimeAtDocumentStart,
                True,
            )
        )
        controller.addUserScript_(user_script)

        request = NSURLRequest.requestWithURL_(
            NSURL.URLWithString_(MENUBAR_URL),
        )
        webview.loadRequest_(request)

        # Keep the webview opaque so its white background is used
        try:
            webview.setValue_forKey_(True, "drawsBackground")
        except Exception:
            pass

        popover = NSPopover.alloc().init()
        popover.setContentSize_(
            (POPOVER_WIDTH, POPOVER_HEIGHT),
        )
        popover.setBehavior_(NSPopoverBehaviorTransient)
        popover.setAnimates_(True)
        # Force the popover chrome to light mode for consistent look
        try:
            from AppKit import NSAppearance

            aqua = NSAppearance.appearanceNamed_("NSAppearanceNameAqua")
            if aqua is not None:
                popover.setAppearance_(aqua)
        except Exception:
            pass

        from AppKit import NSViewController

        vc = NSViewController.alloc().init()
        vc.setView_(webview)
        popover.setContentViewController_(vc)

        self._popover = popover
        self._webview = webview

    # ---- Actions ----

    def togglePopover_(self, sender):  # noqa: N802
        self._ensure_popover()
        button = self.item.button()
        if self._popover.isShown():
            self._popover.performClose_(sender)
        else:
            from AppKit import NSMinYEdge

            # Refresh the UI on each open so data is fresh
            try:
                self._webview.reload()
            except Exception:
                pass
            self._popover.showRelativeToRect_ofView_preferredEdge_(
                button.bounds(), button, NSMinYEdge,
            )
            NSApp().activateIgnoringOtherApps_(True)

    # ---- Message callback ----

    @objc.python_method
    def _on_message(self, body):
        logger.info("Menubar received message: %r", body)
        action = None
        try:
            action = body["action"]
        except Exception:
            try:
                action = body.objectForKey_("action")
            except Exception:
                pass
        if action == "openWindow":
            if self._popover is not None:
                self._popover.performClose_(None)
            if self._window_opener:
                # Defer to next main-loop tick so Cocoa can close
                # the popover cleanly before showing the window
                from Foundation import NSOperationQueue

                NSOperationQueue.mainQueue().addOperationWithBlock_(
                    self._window_opener,
                )
        elif action == "quit":
            if self._popover is not None:
                self._popover.performClose_(None)
            if self._quit_handler:
                try:
                    self._quit_handler()
                except Exception:
                    pass
            NSApp().terminate_(None)
