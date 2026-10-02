#!/usr/bin/env bash
# Build dist/poretrace.app on macOS.
#
# Uses a dedicated conda env with pip-installed PyQt5 (NOT the experiment
# env -- conda's Qt layout is a known PyInstaller minefield). Python 3.12
# is chosen for its mature PyQt5/PyInstaller wheels.
set -euo pipefail
cd "$(dirname "$0")"

ENV_NAME=hekabuild

# 1) clean build env
if [ "$(uname)" = "Darwin" ] && command -v conda >/dev/null; then
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda env list | grep -qE "^${ENV_NAME}[[:space:]]" || conda create -y -n "$ENV_NAME" python=3.12
    conda activate "$ENV_NAME"
else
    echo "conda not found; falling back to python3 venv" >&2
    [ -d build-venv ] || python3 -m venv build-venv
    source build-venv/bin/activate
fi

# 2) dependencies (pip wheels, not conda packages)
python -m pip install --upgrade pip
python -m pip install "pyqt5" "pyqtgraph" "numpy" "pyinstaller"

# 3) build
python -m PyInstaller poretrace.spec --noconfirm --clean

# 4) zip for distribution (ditto preserves the .app bundle structure)
cd dist
ditto -c -k --keepParent poretrace.app poretrace-mac.zip
cd ..

echo
echo "Done: dist/poretrace.app  (+ dist/poretrace-mac.zip)"
echo "Daily use: copy poretrace.app to /Applications (leaves cloud-synced folders)."
echo "First launch on another Mac: right-click -> Open (unsigned app)."
