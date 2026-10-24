#!/usr/bin/env bash
# Stop the demo started by scripts/demo_up.sh: the engine/console and the forensics service.
pkill -f "[s]atyapan serve" && echo "engine stopped" || echo "engine was not running"
pkill -f "[f]orensics.service" && echo "forensics service stopped" || echo "forensics service was not running"
