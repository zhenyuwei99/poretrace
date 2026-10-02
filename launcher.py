"""PyInstaller entry point: launches the Heka .dat browser GUI.

The browser module builds the whole UI at import time and enters the Qt
event loop at the end, so importing it here is the entire app.
"""

from poretrace import browser  # noqa: F401
