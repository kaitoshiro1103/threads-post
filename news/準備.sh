#!/bin/sh
# クラウドの Python に最初から入っている画像の道具（Pillow）は壊れていた（2026年11月17日）。
# そこで news/.venv に自分用の Python を作り、Pillow を入れ直す。2回目からは作り直さない。
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "from PIL import Image" 2>/dev/null; then
  python3 -m venv .venv && .venv/bin/python -m pip install -q --disable-pip-version-check pillow || exit 1
fi
.venv/bin/python -c "from PIL import Image, ImageFont; import PIL; print('準備OK: Pillow', PIL.__version__)"
