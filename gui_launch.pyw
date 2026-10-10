"""
Double-click-friendly launcher. Identical to gui.py, but with a .pyw
extension: Windows runs .pyw files with pythonw.exe automatically, so no
console window is created in the first place (better than gui.py's
_hide_console(), which briefly shows/hides one when run via `python gui.py`).

Usage: just double-click gui_launch.pyw, or `pythonw gui_launch.pyw`.
"""
from gui import CommandBar

if __name__ == "__main__":
    CommandBar().mainloop()
