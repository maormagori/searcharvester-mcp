#!/usr/bin/env bash
set -euo pipefail

USER="admin"
PASS="zH_2R!!EXkXsMX"
HOST="https://searcharvester.magori.xyz"

SESSION=$(curl -si -X POST "$HOST/mcp/" \
  -u "$USER:$PASS" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}' \
  | grep -i mcp-session-id | awk '{print $2}' | tr -d '\r')

curl -s -X POST "$HOST/mcp/" \
  -u "$USER:$PASS" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":2,"params":{}}' | grep "^data:" | sed 's/^data: //' | python3 -m json.tool
