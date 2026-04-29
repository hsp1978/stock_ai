.PHONY: help up down restart build rebuild logs logs-agent logs-webui ps health urls shell-agent shell-webui

help:           ## 명령 목록
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "} {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

up:             ## dev 프로파일 기동 (background)
	docker compose --profile dev up -d

down:           ## 컨테이너 종료 (이미지/볼륨 보존)
	docker compose --profile dev down

restart: down up   ## down → up (이미지 재빌드 없음)

build:          ## 이미지 빌드
	docker compose --profile dev build

rebuild: down build up   ## down → build → up

logs:           ## 두 컨테이너 로그 follow
	docker compose --profile dev logs -f

logs-agent:     ## agent-api 로그 follow
	docker compose --profile dev logs -f agent-api

logs-webui:     ## webui 로그 follow
	docker compose --profile dev logs -f webui

ps:             ## 컨테이너 상태
	docker compose ps

health:         ## /health endpoint JSON 출력
	@curl -sS --max-time 5 http://localhost:8100/health | python3 -m json.tool

urls:           ## 접속 URL 출력
	@echo "WebUI:    http://localhost:8501"
	@echo "Agent API: http://localhost:8100/health"

shell-agent:    ## agent-api 컨테이너 shell
	docker exec -it stock-auto-agent-api bash

shell-webui:    ## webui 컨테이너 shell
	docker exec -it stock-auto-webui bash
