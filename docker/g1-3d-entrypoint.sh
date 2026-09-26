#!/bin/sh
set -eu

if [ -z "${BYTEPLUS_API_KEY:-}" ]; then
  echo "error: BYTEPLUS_API_KEY must be set to run this image" >&2
  exit 1
fi

exec "$@"
