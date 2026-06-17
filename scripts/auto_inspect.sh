#!/usr/bin/env bash
set -u

section() {
  echo
  echo "######## $1 ########"
}

run_if_exists() {
  local command_name="$1"
  shift
  if command -v "$command_name" >/dev/null 2>&1; then
    "$@" 2>&1
  else
    echo "$command_name command is unavailable."
  fi
}

echo "== Auto inspection started at $(date '+%F %T') =="

section "System overview"
echo "Hostname: $(hostname 2>/dev/null || echo unknown)"
run_if_exists uptime uptime
run_if_exists who who

section "Recent logins"
if command -v last >/dev/null 2>&1; then
  last -n 10 2>/dev/null || true
else
  echo "last command is unavailable."
fi

section "Disk and inode pressure"
df -h 2>&1
echo
df -i 2>&1
echo
echo "Filesystems above 80 percent:"
df -P 2>/dev/null | awk 'NR > 1 {
  pct=$5
  gsub("%", "", pct)
  if (pct + 0 >= 80) print $0
}'

section "Large log files"
if [ -d /var/log ]; then
  find /var/log -xdev -type f -size +100M -printf '%s %p\n' 2>/dev/null \
    | sort -n | tail -20 | awk '{
      size=$1
      $1=""
      printf "%.1f MiB%s\n", size / 1024 / 1024, $0
    }'
else
  echo "/var/log does not exist on this system."
fi

section "Memory and load"
run_if_exists free free -h
echo
if command -v top >/dev/null 2>&1; then
  top -b -n 1 2>/dev/null | head -5
else
  echo "top command is unavailable."
fi

section "Top CPU processes"
ps aux --sort=-%cpu 2>/dev/null | head -11

section "Top memory processes"
ps aux --sort=-%mem 2>/dev/null | head -11

section "Network addresses and routes"
run_if_exists ip ip -brief addr
echo
run_if_exists ip ip route

section "Listening ports"
if command -v ss >/dev/null 2>&1; then
  ss -tulnp 2>/dev/null | head -80
else
  echo "ss command is unavailable."
fi

section "Failed systemd units"
if command -v systemctl >/dev/null 2>&1; then
  systemctl --failed --no-pager 2>/dev/null || true
else
  echo "systemctl command is unavailable."
fi

section "Recent warning and error logs"
if command -v journalctl >/dev/null 2>&1; then
  journalctl -p warning..alert --since "24 hours ago" --no-pager 2>/dev/null | tail -80
elif [ -r /var/log/syslog ]; then
  grep -Ei 'error|warn|fail|critical' /var/log/syslog 2>/dev/null | tail -80
elif [ -r /var/log/messages ]; then
  grep -Ei 'error|warn|fail|critical' /var/log/messages 2>/dev/null | tail -80
else
  echo "No readable journalctl, syslog, or messages source found."
fi

section "Recent authentication failures"
AUTH_LOG=""
if [ -n "${AUTH_LOG_FILE:-}" ] && [ -r "${AUTH_LOG_FILE:-}" ]; then
  AUTH_LOG="$AUTH_LOG_FILE"
elif [ -r /var/log/auth.log ]; then
  AUTH_LOG="/var/log/auth.log"
elif [ -r /var/log/secure ]; then
  AUTH_LOG="/var/log/secure"
fi

if [ -n "$AUTH_LOG" ]; then
  grep -Ei 'failed|failure|invalid|authentication failure' "$AUTH_LOG" 2>/dev/null | tail -40
else
  echo "No readable auth log file found."
fi

echo
echo "== Auto inspection finished at $(date '+%F %T') =="
