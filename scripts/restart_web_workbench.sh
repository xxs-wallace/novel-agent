#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

API_PORT=8000
WEB_PORT=5173
STOP_ONLY=0
OPEN_BROWSER=1
DAEMON=1
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
Usage: scripts/restart_web_workbench.sh [options] [-- extra novel-agent-web args]

Options:
  --api-port PORT   FastAPI port to start after stopping old web processes. Default: 8000
  --web-port PORT   Vite port to start after stopping old web processes. Default: 5173
  --stop-only       Stop matching web processes and do not start a new workbench.
  --no-open         Start without opening a browser.
  --open            Start and open a browser. Default.
  --daemon          Start in the background and wait for ports. Default.
  --foreground      Keep the launcher attached to the current terminal.
  -h, --help        Show this help.

The stop phase scans the default and recent workbench ports: 8000, 5173, 8010, 5174,
plus any ports passed with --api-port/--web-port. It only kills processes that look
like this repository's Novel Agent Web backend/frontend.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-port)
      API_PORT="${2:?missing value for --api-port}"
      shift 2
      ;;
    --web-port)
      WEB_PORT="${2:?missing value for --web-port}"
      shift 2
      ;;
    --stop-only)
      STOP_ONLY=1
      shift
      ;;
    --no-open)
      OPEN_BROWSER=0
      shift
      ;;
    --open)
      OPEN_BROWSER=1
      shift
      ;;
    --daemon)
      DAEMON=1
      shift
      ;;
    --foreground)
      DAEMON=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      EXTRA_ARGS+=("$@")
      break
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

unique_ports() {
  printf "%s\n" "$@" | awk 'NF && !seen[$0]++'
}

is_repo_web_process() {
  local pid="$1"
  local command
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ -n "$command" ]] || return 1
  case "$command" in
    *"novel_agent.app.web.main:app"*|\
    *"cli.novel_agent_web"*|\
    *"$REPO_ROOT"*"novel_agent.app.web.main:app"*|\
    *"$REPO_ROOT"*"cli.novel_agent_web"*|\
    *"$REPO_ROOT/web"*"vite"*|\
    *"$REPO_ROOT/web"*"npm run dev"*)
      return 0
      ;;
  esac
  return 1
}

stop_pid() {
  local pid="$1"
  local command
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ -n "$command" ]] || return 0

  echo "Stopping PID $pid: $command"
  kill "$pid" 2>/dev/null || true

  for _ in 1 2 3 4 5; do
    sleep 0.2
    if ! ps -p "$pid" >/dev/null 2>&1; then
      return 0
    fi
  done

  echo "PID $pid did not exit after TERM; sending KILL."
  kill -9 "$pid" 2>/dev/null || true
}

stop_ports() {
  local ports
  ports="$(unique_ports 8000 5173 8010 5174 "$API_PORT" "$WEB_PORT")"
  local killed=0
  while IFS= read -r port; do
    [[ -n "$port" ]] || continue
    local pids
    pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    [[ -n "$pids" ]] || continue
    while IFS= read -r pid; do
      [[ -n "$pid" ]] || continue
      if is_repo_web_process "$pid"; then
        stop_pid "$pid"
        killed=1
      else
        local command
        command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
        echo "Skipping non Novel Agent Web process on port $port, PID $pid: $command"
      fi
    done <<< "$pids"
  done <<< "$ports"

  if [[ "$killed" -eq 0 ]]; then
    echo "No matching Novel Agent Web processes were listening on known ports."
  fi
}

stop_ports

if [[ "$STOP_ONLY" -eq 1 ]]; then
  exit 0
fi

START_ARGS=(--api-port "$API_PORT" --web-port "$WEB_PORT")
if [[ "$OPEN_BROWSER" -eq 0 ]]; then
  START_ARGS+=(--no-open)
fi

echo "Starting Novel Agent Web: API http://127.0.0.1:$API_PORT, Web http://127.0.0.1:$WEB_PORT"
cd "$REPO_ROOT"
COMMAND=(./novel-agent-web "${START_ARGS[@]}")
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  COMMAND+=("${EXTRA_ARGS[@]}")
fi

if [[ "$DAEMON" -eq 0 ]]; then
  exec "${COMMAND[@]}"
fi

LOG_DIR="$REPO_ROOT/runs/logs"
mkdir -p "$LOG_DIR"
LAUNCHER_STDIO_LOG="$LOG_DIR/web_launcher_daemon.log"
DETACH_PYTHON="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$DETACH_PYTHON" ]]; then
  DETACH_PYTHON="$(command -v python3)"
fi
LAUNCHER_PID="$(
  "$DETACH_PYTHON" - "$REPO_ROOT" "$LAUNCHER_STDIO_LOG" "${COMMAND[@]}" <<'PY'
import os
import sys

repo_root, log_path, *command = sys.argv[1:]
pid = os.fork()
if pid:
    print(pid, flush=True)
    raise SystemExit(0)

os.setsid()
log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
try:
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
finally:
    os.close(log_fd)
os.chdir(repo_root)
os.execvpe(command[0], command, os.environ.copy())
PY
)"
echo "Launcher PID $LAUNCHER_PID. 启动器输出：$LAUNCHER_STDIO_LOG"

wait_for_port() {
  local port="$1"
  local label="$2"
  for _ in $(seq 1 80); do
    if lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      return 0
    fi
    if ! kill -0 "$LAUNCHER_PID" 2>/dev/null; then
      echo "$label 未启动：launcher 已退出。最近输出："
      tail -80 "$LAUNCHER_STDIO_LOG" 2>/dev/null || true
      return 1
    fi
    sleep 0.25
  done
  echo "$label 未在等待时间内监听端口 $port。最近输出："
  tail -80 "$LAUNCHER_STDIO_LOG" 2>/dev/null || true
  return 1
}

wait_for_port "$API_PORT" "后端"
wait_for_port "$WEB_PORT" "前端"
echo "Novel Agent Web 已启动：API http://127.0.0.1:$API_PORT, Web http://127.0.0.1:$WEB_PORT"
