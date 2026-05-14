#!/usr/bin/env bash
# cleanup-sessions.sh — Kill orphaned JUGO tmux sessions
# Removes all tmux sessions matching the JUGO prefix that are NOT
# currently referenced by active JUGO sessions in the API.
#
# Usage: ./cleanup-sessions.sh [--dry-run]

set -uo pipefail

JUGO_API="${JUGO_API:-http://127.0.0.1:11001}"
DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

# 1. Get prefix from env or default
PREFIX="${JUGO_TMUX_SESSION_PREFIX:-jugo}"

# 2. Get active panes from JUGO API
active_panes=$(curl -sS "$JUGO_API/session/list" 2>/dev/null \
  | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for s in d.get('sessions', []):
        p = s.get('pane', '')
        if p:
            sess = p.split(':')[0]
            print(sess)
except: pass
" 2>/dev/null || true)

# 3. List all tmux sessions with the JUGO prefix
all_jugo=$(tmux list-sessions -F '#{session_name}' 2>/dev/null \
  | grep "^${PREFIX}_" || true)

if [[ -z "$all_jugo" ]]; then
    echo "No JUGO tmux sessions found."
    exit 0
fi

killed=0
kept=0

while IFS= read -r session; do
    if echo "$active_panes" | grep -qxF "$session"; then
        echo "  KEEP  $session (active in JUGO)"
        ((kept++))
    else
        if $DRY_RUN; then
            echo "  WOULD KILL  $session"
        else
            tmux kill-session -t "$session" 2>/dev/null && \
                echo "  KILLED  $session" || \
                echo "  FAILED  $session"
        fi
        ((killed++))
    fi
done <<< "$all_jugo"

echo ""
if $DRY_RUN; then
    echo "Dry run: would kill $killed, keep $kept"
else
    echo "Done: killed $killed, kept $kept"
fi
