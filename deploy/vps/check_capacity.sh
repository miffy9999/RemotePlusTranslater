#!/usr/bin/env sh
set -eu

STRICT=0
if [ "${1:-}" = "--strict" ]; then
    STRICT=1
elif [ "$#" -ne 0 ]; then
    echo "usage: check_capacity.sh [--strict]" >&2
    exit 64
fi
MIN_AVAILABLE_MB=${MIN_AVAILABLE_MB:-700}
MIN_DISK_MB=${MIN_DISK_MB:-4096}

echo "== host =="
uname -a
echo "== memory (MB) =="
if command -v free >/dev/null 2>&1; then free -m; else cat /proc/meminfo; fi
echo "== disk =="
df -h /
echo "== swap and pressure =="
if command -v swapon >/dev/null 2>&1; then swapon --show || true; fi
if command -v vmstat >/dev/null 2>&1; then vmstat 1 5; else echo "vmstat unavailable"; fi
echo "== listening ports =="
if command -v ss >/dev/null 2>&1; then ss -lntup; else echo "ss unavailable"; fi
echo "== largest processes =="
ps -eo pid,comm,%cpu,%mem,rss --sort=-rss | head -n 16
echo "== failed services =="
if command -v systemctl >/dev/null 2>&1; then systemctl --failed --no-pager || true; fi
echo "== OOM evidence =="
if command -v journalctl >/dev/null 2>&1; then
    OOM_EVIDENCE=$(journalctl -k --since '24 hours ago' --no-pager 2>/dev/null | \
        grep -Ei 'oom|out of memory|killed process' || true)
    if [ -n "$OOM_EVIDENCE" ]; then printf '%s\n' "$OOM_EVIDENCE"; else echo "none visible"; fi
else
    OOM_EVIDENCE=""
    echo "journalctl unavailable"
fi

AVAILABLE_MB=$(awk '/MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo)
DISK_LINE=$(df -Pm /srv 2>/dev/null | awk 'NR==2 {print $4 " " $5}')
if [ -z "$DISK_LINE" ]; then
    DISK_LINE=$(df -Pm / | awk 'NR==2 {print $4 " " $5}')
fi
DISK_MB=$(printf '%s\n' "$DISK_LINE" | awk '{print $1}')
DISK_USED_PERCENT=$(printf '%s\n' "$DISK_LINE" | awk '{gsub(/%/, "", $2); print $2}')
FAILED=0
if [ "$AVAILABLE_MB" -lt "$MIN_AVAILABLE_MB" ]; then
    echo "FAIL: available memory ${AVAILABLE_MB}MB < ${MIN_AVAILABLE_MB}MB" >&2
    FAILED=1
else
    echo "PASS: available memory ${AVAILABLE_MB}MB"
fi
if [ "$DISK_MB" -lt "$MIN_DISK_MB" ]; then
    echo "FAIL: available disk ${DISK_MB}MB < ${MIN_DISK_MB}MB" >&2
    FAILED=1
else
    echo "PASS: available disk ${DISK_MB}MB"
fi
if [ "$DISK_USED_PERCENT" -gt 80 ]; then
    echo "FAIL: disk usage ${DISK_USED_PERCENT}% > 80%" >&2
    FAILED=1
else
    echo "PASS: disk usage ${DISK_USED_PERCENT}%"
fi
if [ -n "$OOM_EVIDENCE" ]; then
    echo "FAIL: OOM evidence exists in the last 24 hours" >&2
    FAILED=1
fi
if [ "$STRICT" -eq 1 ] && [ "$FAILED" -ne 0 ]; then
    exit 1
fi
