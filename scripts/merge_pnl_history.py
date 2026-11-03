"""Union-merge local pnl_history.json with origin/main version.

Called by pnl-check.yml when a push is rejected (concurrent workflow runs).
Combines both sides by date key so no entries are lost.
"""
import json
import subprocess
import sys
from pathlib import Path

HISTORY = Path("state/pnl_history.json")

try:
    remote_json = subprocess.check_output(
        ["git", "show", "origin/main:state/pnl_history.json"],
        stderr=subprocess.DEVNULL,
    ).decode()
    remote = json.loads(remote_json)
except Exception:
    remote = []

try:
    local = json.loads(HISTORY.read_text(encoding="utf-8"))
except Exception:
    local = []

merged = {e["date"]: e for e in remote}
for e in local:
    if e.get("date") not in merged:
        merged[e["date"]] = e

result = sorted(merged.values(), key=lambda e: e.get("date", ""))
HISTORY.write_text(json.dumps(result, indent=2), encoding="utf-8")
print(f"merge_pnl_history: {len(result)} entries total")
