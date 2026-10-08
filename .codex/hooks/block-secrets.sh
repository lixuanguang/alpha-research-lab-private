#!/bin/sh
# PreToolUse guard: refuse tool calls that reference local credential files.
# Inspects only the command/path/pattern/glob fields (not free-text descriptions)
# and matches the secrets directory as a path token, any *.secrets file, and the
# other credential files kept there. Templates ending in .secrets.example stay
# allowed. Exit 2 blocks the call and reports the reason to Claude.
input=$(cat)
payload=$(printf '%s' "$input" | jq -r '.tool_input | [.command, .path, .pattern, .glob] | map(select(. != null)) | join("\n")' 2>/dev/null) || payload=$input
pattern='(^|[^A-Za-z0-9_.-])secrets([^A-Za-z0-9_.-]|$)|\.secrets([^.A-Za-z0-9_]|$)|lakefs-credentials|local-services\.env'
if printf '%s' "$payload" | grep -Eq "$pattern"; then
  echo "Blocked: this call references local credential files (secrets/ or *.secrets); they must never be read." >&2
  exit 2
fi
exit 0
