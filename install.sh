#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${HOME}/.gemini/config/plugins/conversation-history"

mkdir -p "$(dirname "$TARGET_DIR")"

if [ "$SCRIPT_DIR" = "$TARGET_DIR" ]; then
  echo "[conversation-history] Already installed at: $TARGET_DIR"
else
  rm -rf "$TARGET_DIR"
  mkdir -p "$TARGET_DIR"
  cp -a "$SCRIPT_DIR"/. "$TARGET_DIR"/
  rm -rf "$TARGET_DIR/.git" "$TARGET_DIR/.state"
  echo "[conversation-history] Installed to: $TARGET_DIR"
fi

python3 -m unittest discover -s "$TARGET_DIR/tests" -v
echo "[conversation-history] Ready! Restart or open any Antigravity session to use it."
