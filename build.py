#!/usr/bin/env python3
"""Build a standalone Windows exe with PyInstaller.

Usage:
    pip install -r requirements.txt
    pip install pyinstaller
    python build.py

Output: dist/ADBConsole.exe (double-click to run; opens the browser and adds a
system tray icon; close it from the tray menu).
"""

import subprocess
import sys

NAME = "ADBConsole"

ARGS = [
    sys.executable,
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--windowed",
    "--name",
    NAME,
    "--add-data",
    "templates;templates",
    "--add-data",
    "static;static",
    "--hidden-import",
    "pystray._win32",
    "--hidden-import",
    "six",
    "--hidden-import",
    "PIL.Image",
    "--hidden-import",
    "PIL.ImageDraw",
    "run.py",
]


def main() -> None:
    print("Building", NAME, "...")
    result = subprocess.run(ARGS)
    if result.returncode != 0:
        sys.exit(f"PyInstaller failed with exit code {result.returncode}")
    print(f"Done: dist/{NAME}.exe")


if __name__ == "__main__":
    main()
