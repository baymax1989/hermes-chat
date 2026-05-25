#!/bin/bash
# Hermes Chat — One-command launcher
# Usage: ./start.sh [api-key]

if [ -z "$HERMES_API_KEY" ] && [ -n "$1" ]; then
  export HERMES_API_KEY="$1"
fi

if [ -z "$HERMES_API_KEY" ]; then
  echo "Error: HERMES_API_KEY not set."
  echo "Usage: ./start.sh your-api-key"
  echo "   or: export HERMES_API_KEY=your-key && ./start.sh"
  exit 1
fi

echo "Starting Hermes Chat on http://localhost:8080 ..."
python3 hermes-chat-server.py
