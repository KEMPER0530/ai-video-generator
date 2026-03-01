#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE_NAME="ai-video-generator-pipeline:latest"

if [[ "${1:-}" == "--build" ]]; then
  docker build -f "$ROOT_DIR/docker/Dockerfile" -t "$IMAGE_NAME" "$ROOT_DIR"
  shift
fi

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 [--build] <run.py args...>"
  echo "Example: $0 --build all --config configs/config.docker.cpu.json --story stories/story.aws.json"
  exit 1
fi

TTY_FLAGS="-i"
if [[ -t 1 ]]; then
  TTY_FLAGS="-it"
fi

exec docker run --rm ${TTY_FLAGS} \
  -v "$ROOT_DIR:/work" \
  -w /work \
  "$IMAGE_NAME" "$@"
