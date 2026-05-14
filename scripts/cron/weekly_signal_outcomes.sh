#!/usr/bin/env bash
# 매주 일요일 22:00 KST signal_outcomes 배치 평가
# crontab 등록 예: 0 13 * * 0 /home/ubuntu/stock_auto/scripts/cron/weekly_signal_outcomes.sh
set -euo pipefail

cd /home/ubuntu/stock_auto
docker compose --profile dev exec -T agent-api \
    python -m chart_agent_service.jobs.evaluate_signal_outcomes
