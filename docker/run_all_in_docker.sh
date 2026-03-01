#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE_NAME="ai-video-generator-pipeline:latest"

cd "$ROOT_DIR"

echo "[1/2] Build pipeline image"
docker build -f docker/Dockerfile -t "$IMAGE_NAME" .

echo "[2/2] Run pipeline"
docker run --rm \
  -v "$ROOT_DIR:/work" \
  -w /work \
  "$IMAGE_NAME" \
  all --config configs/config.docker.cpu.json --story stories/story.aws.json

echo "[done] outputs are under $ROOT_DIR/outputs/docker-all"
