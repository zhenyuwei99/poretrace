#!/usr/bin/env bash
# Build dist/HekaBrowser on Linux (single file, chmod +x to run).
#
# IMPORTANT: build on the OLDEST distro you want to support (e.g. Ubuntu
# 22.04) -- the resulting binary requires at most the glibc of the build
# machine. Building on 24.04 will NOT run on 22.04.
set -euo pipefail
cd "$(dirname "$0")"

PY=python3.12
command -v "$PY" >/dev/null 2>&1 || PY=python3

[ -d build-venv ] || "$PY" -m venv build-venv
source build-venv/bin/activate

python -m pip install --upgrade pip
python -m pip install pyqt5 pyqtgraph numpy pyinstaller

python -m PyInstaller heka_browser.spec --noconfirm --clean

# zip for distribution
cd dist
zip -qry HekaBrowser-linux.zip HekaBrowser
cd ..

echo
echo "Done: dist/HekaBrowser/HekaBrowser  (+ dist/HekaBrowser-linux.zip)"
echo "Unzip anywhere, then: chmod +x HekaBrowser && ./HekaBrowser"
