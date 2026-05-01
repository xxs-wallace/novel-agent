#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$REPO_ROOT/.venv"

choose_python() {
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    echo "$VENV_DIR/bin/python"
    return 0
  fi

  local candidates=(
    "python3.12"
    "python3.11"
    "python3.10"
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$(command -v "$candidate")"
      return 0
    fi
  done

  echo "未找到 Python 3.10+ 解释器。请先安装 python3.10 / python3.11 / python3.12。" >&2
  return 1
}

ensure_python_version() {
  local python_bin="$1"
  "$python_bin" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("当前解释器版本低于 3.10，无法运行本项目。")
PY
}

ensure_venv() {
  local base_python="$1"
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "创建虚拟环境: $VENV_DIR"
    "$base_python" -m venv "$VENV_DIR"
  fi
}

ensure_dependencies() {
  local python_bin="$1"
  if "$python_bin" - <<'PY' >/dev/null 2>&1
import importlib
mods = [
    "smolagents",
    "openai",
    "jieba",
    "dotenv",
    "requests",
    "rich",
    "jinja2",
    "PIL",
]
for mod in mods:
    importlib.import_module(mod)
PY
  then
    return 0
  fi

  echo "检测到缺失依赖，开始安装..."
  "$python_bin" -m pip install --upgrade pip setuptools wheel
  "$python_bin" -m pip install -e "$REPO_ROOT[openai]" PyYAML
}

BASE_PYTHON="$(choose_python)"
ensure_python_version "$BASE_PYTHON"
ensure_venv "$BASE_PYTHON"

PYTHON_BIN="$VENV_DIR/bin/python"
ensure_python_version "$PYTHON_BIN"
ensure_dependencies "$PYTHON_BIN"

export PYTHONPATH="$REPO_ROOT/src:$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "使用解释器: $PYTHON_BIN"
exec "$PYTHON_BIN" -m novel_agent.app.run_single_sample_smoke "$@"
