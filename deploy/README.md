# deploy/

부팅 시 자동 기동을 위한 systemd unit.

## 설치

```bash
sudo cp deploy/stock-auto.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stock-auto.service
sudo systemctl status stock-auto.service
```

`enable --now` 한 번이면 즉시 기동 + 부팅 시 자동.

## 동작

- `Type=oneshot` + `RemainAfterExit=yes` — `docker compose up -d` 가 detached 라 systemd 입장에선 한 번 실행 후 끝나는 task. compose 가 띄운 컨테이너는 docker daemon 이 관리.
- `Requires=docker.service` — Docker 데몬이 살아있어야 하고, 데몬 종료 시 unit도 종료.
- `User=ubuntu` — 사용자 docker group 권한 필요 (`groups ubuntu` 에 `docker` 포함 확인).

## 운영 명령

| 의도 | 명령 |
|---|---|
| 즉시 기동 | `sudo systemctl start stock-auto` |
| 즉시 종료 | `sudo systemctl stop stock-auto` |
| 재시작 | `sudo systemctl restart stock-auto` |
| 로그 (systemd 측) | `journalctl -u stock-auto -f` |
| 로그 (compose 측) | `make logs` 또는 `docker compose logs -f` |
| 상태 | `systemctl status stock-auto` |

## 비활성화 (수동 운영으로 복귀)

```bash
sudo systemctl disable --now stock-auto.service
# 이후 make up / make down 으로 수동 운영
```

## Phase 4에서 비활성화한 V1 unit

배포 리팩토링 중 native 운영용 `stock-webui.service` / `stock-bot.service` 는 disable 됨 (`docs/DEPLOY_BASELINE.md` Phase 4 결과 참조). compose 가 같은 역할을 대체.
