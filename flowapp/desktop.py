"""Windows desktop integration: the desktop shortcut and the taskbar identity."""

import subprocess
import sys

from .config import ASSETS_DIR, ROOT

APP_ID = "FlowControllers.FlowApp"
SHORTCUT_NAME = "Flow controllers.lnk"
ICON = ASSETS_DIR / "logo.ico"
LAUNCHER = ROOT / "run.bat"


def _ps_quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def shortcut_script(target=LAUNCHER, icon=ICON, name=SHORTCUT_NAME):
    """PowerShell that creates or updates the shortcut on the user's desktop (also a OneDrive desktop)."""
    return "; ".join([
        "$desktop = [Environment]::GetFolderPath('Desktop')",
        f"$link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop {_ps_quote(name)}))",
        f"$link.TargetPath = {_ps_quote(target)}",
        f"$link.WorkingDirectory = {_ps_quote(target.parent)}",
        f"$link.IconLocation = {_ps_quote(f'{icon},0')}",
        "$link.WindowStyle = 7",        # the launcher's console starts minimized
        "$link.Description = 'Bronkhorst flow controllers: instruments or test mode'",
        "$link.Save()",
        "Write-Output $link.FullName",
    ])


def create_desktop_shortcut(run=subprocess.run):
    """Creates (or updates) the desktop shortcut to run.bat. Returns the shortcut's path."""
    if sys.platform != "win32":
        raise OSError("Desktop shortcuts are only created on Windows.")
    result = run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                  "-Command", shortcut_script()],
                 capture_output=True, text=True, timeout=60,
                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or f"PowerShell exited with {result.returncode}")
    return result.stdout.strip()


def set_taskbar_identity():
    """Lets Windows show the app's own icon in the taskbar instead of Python's."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass
