#!/usr/bin/env bash
# Run the in-process evaluation experiments in full, one after the other (never two at once: the
# 2-core, 4 GB laptop is the target hardware, and parallel runs distort each other's timings).
# Each run writes results/<ID>/ and a log in var/log/full_<ID>.log.
#
#   bash evaluation/run_full.sh [E1 E9 E2 E4 E3]       (from backend/, local database running)
set -u
cd "$(dirname "$0")/.."
export PYTHONUTF8=1 PYTHONNOUSERSITE=1
export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:@127.0.0.1:26029/postgres?sslmode=disable}"
LOGS=../var/log
mkdir -p "$LOGS"
declare -A COMMAND=(
  [E1]="-m evaluation.e1_replication --days 1"
  [E2]="-m evaluation.e2_forecast"
  [E3]="-m evaluation.e3_early_warning"
  [E4]="-m evaluation.e4_sim_vs_reality"
  [E9]="-m evaluation.e9_capacity"
)
for id in "${@:-E1 E9 E2 E4 E3}"; do
  for x in $id; do
    started=$(date +%s)
    echo "$(date '+%F %T') $x started: python ${COMMAND[$x]}" | tee -a "$LOGS/full_runs.log"
    .venv/Scripts/python ${COMMAND[$x]} > "$LOGS/full_$x.log" 2>&1
    code=$?
    echo "$(date '+%F %T') $x finished with exit code $code after $(( ($(date +%s) - started) / 60 )) min" \
      | tee -a "$LOGS/full_runs.log"
  done
done
