#!/usr/bin/env bash
# Builds dist/innerlogic-sentinel-connector.zip for WEBSITE_RUN_FROM_PACKAGE.
# Dependencies are vendored for Azure Functions Linux (x86_64, Python 3.11)
# regardless of the machine this runs on.
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=dist/innerlogic-sentinel-connector.zip
rm -rf build dist
mkdir -p build dist

cp -r function_app.py host.json requirements.txt innerlogic_sentinel build/
python3 -m pip install --quiet --upgrade --no-compile --target build/.python_packages/lib/site-packages \
  --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 \
  --python-version 3.11 --implementation cp --only-binary=:all: \
  -r requirements.txt

find build -name '__pycache__' -type d -prune -exec rm -rf {} +
(cd build && python3 -c "
import os, sys, zipfile
with zipfile.ZipFile('../$OUT', 'w', zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk('.'):
        for f in files:
            p = os.path.join(root, f)
            z.write(p, os.path.relpath(p, '.'))
")
echo "Built sentinel/$OUT ($(du -h "$OUT" | cut -f1))"
