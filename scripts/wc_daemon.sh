#!/usr/bin/env bash
# Supervisor for the FIFA World Cup data fetcher.
# Keeps wc_fetch.py running forever; restarts it if it ever exits.
# Usage:
#   scripts/wc_daemon.sh start    # launch in background (survives logout)
#   scripts/wc_daemon.sh stop     # stop it
#   scripts/wc_daemon.sh status   # show status + tail of log
#   scripts/wc_daemon.sh run      # run in foreground (used internally)

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$SCRIPT_DIR/wc_fetch.log"
PID_FILE="$SCRIPT_DIR/wc_daemon.pid"
PY="$(command -v python3)"

run_loop() {
  echo "[wc_daemon] supervisor started pid=$$ $(date)" >> "$LOG_FILE"
  while true; do
    "$PY" "$SCRIPT_DIR/wc_fetch.py" >> "$LOG_FILE" 2>&1
    echo "[wc_daemon] fetcher exited ($?), restarting in 30s $(date)" >> "$LOG_FILE"
    sleep 30
  done
}

case "${1:-start}" in
  run)
    run_loop
    ;;
  start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "Already running (pid $(cat "$PID_FILE"))."
      exit 0
    fi
    setsid "$SCRIPT_DIR/wc_daemon.sh" run < /dev/null >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    echo "Started FIFA WC fetcher (pid $(cat "$PID_FILE")). Log: $LOG_FILE"
    ;;
  stop)
    if [ -f "$PID_FILE" ]; then
      PID="$(cat "$PID_FILE")"
      # kill the supervisor and its process group
      pkill -P "$PID" 2>/dev/null
      kill "$PID" 2>/dev/null
      pkill -f "wc_fetch.py" 2>/dev/null
      rm -f "$PID_FILE"
      echo "Stopped."
    else
      pkill -f "wc_fetch.py" 2>/dev/null && echo "Stopped (by name)." || echo "Not running."
    fi
    ;;
  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "RUNNING (supervisor pid $(cat "$PID_FILE"))"
    else
      echo "NOT RUNNING"
    fi
    echo "--- last 15 log lines ---"
    tail -n 15 "$LOG_FILE" 2>/dev/null || echo "(no log yet)"
    ;;
  *)
    echo "Usage: $0 {start|stop|status|run}"
    exit 1
    ;;
esac
