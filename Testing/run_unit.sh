#!/usr/bin/env bash
cd "$(dirname "$0")/.." || exit 1
uv run --python 3.12 --with pytest --with numpy python -m pytest Testing/unit -q
