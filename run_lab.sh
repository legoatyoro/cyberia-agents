#!/bin/bash
set -a
source /root/cyberia/.env
set +a
cd /root/cyberia
source venv/bin/activate
exec python3 evolve_live_v2.py "$@"
