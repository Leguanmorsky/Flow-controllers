"""Starts the graphical app."""

import sys
import traceback

import pyqtgraph as pg
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ..config import ASSETS_DIR, ROOT
from ..desktop import set_taskbar_identity
from .main_window import MainWindow

# Windows console events: close button, log off, shut down
_CONSOLE_CLOSE_EVENTS = {2, 5, 6}


def _zero_when_console_closes(window):
    """Closing the console window kills Python without closeEvent: set the flows to 0 first."""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

    def handler(event):
        if event in _CONSOLE_CLOSE_EVENTS:
            window.bridge.emergency_zero()
        return False    # continue with the default handling (the process ends)

    window._console_handler = handler_type(handler)     # keep a reference for the lifetime of the window
    ctypes.windll.kernel32.SetConsoleCtrlHandler(window._console_handler, True)


def _log_to_file_without_console():
    """pythonw (run.bat, desktop shortcut) has no console: keep the log and any error in logs/last_run.log."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    folder = ROOT / "logs"
    folder.mkdir(exist_ok=True)
    stream = open(folder / "last_run.log", "w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = stream


def run_gui(settings):
    _log_to_file_without_console()
    set_taskbar_identity()
    pg.setConfigOptions(antialias=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Flow controllers")
    app.setWindowIcon(QIcon(str(ASSETS_DIR / "logo.ico")))
    window = MainWindow(settings)

    def excepthook(exc_type, exc, tb):
        traceback.print_exception(exc_type, exc, tb)
        try:
            window.log_event("error", f"Unexpected error: {exc_type.__name__}: {exc}")
        except Exception:
            pass

    previous_hook = sys.excepthook
    sys.excepthook = excepthook
    _zero_when_console_closes(window)
    window.show()
    try:
        return app.exec()
    finally:
        sys.excepthook = previous_hook
