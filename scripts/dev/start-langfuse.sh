#!/usr/bin/env bash
# Thin wrapper: Langfuse compose lives under docker/docker-compose/langfuse/ (see README there).
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../docker/docker-compose/langfuse/start.sh" "$@"
