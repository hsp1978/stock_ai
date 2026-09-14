# 백업·복구 런북

> testdev 한 대가 죽으면 시스템 전체가 정지한다 (SPOF). 이 문서는 **무엇을 잃는지**와
> **어떻게 되돌리는지**를 적는다. 절차는 실제로 한 번 돌려보기 전까지 검증된 게 아니다.

## 1. 무엇을 백업하는가

재생성이 **불가능한 것만** 담는다.

| 대상 | 내용 | 잃으면 |
|---|---|---|
| `output/scan_log.db` | 스캔 이력 70,840행, `signal_outcomes` 5,442건, `app_state` | 60일 검증 시계가 0부터 다시. 칼리브레이션·IC 표본 소멸 |
| `output/paper_trading_state.json` | 페이퍼 포지션·체결 이력 | 성과 추적 단절 |
| `output/trading_safety.db` | 킬스위치·안전장치 상태 | 안전장치 이력 소실 |
| `output/approval_queue.db` / `order_audit.db` | 승인 대기·주문 감사 로그 | 감사 추적 불가 |
| `data/scan_history.db` | 스캐너 히스토리 | 스캐너 이력 소실 |
| `stock_analyzer/watchlist.txt` | 워치리스트 SSOT | 재입력 가능(경미) |

**담지 않는 것**: 분석 JSON(쓰기 전용, 재생성 가능), 차트 PNG, 모델 캐시.
`output_retention` 잡이 따로 관리한다.

**`.env` 는 기본 미포함이다.** 키 60여 개가 들어 있어 백업 파일이 곧 자격증명 사본이
된다. 넣으려면 `include_env=True` 를 명시해야 하고, 그 아카이브는 저장소·공유
드라이브에 올리지 않는다.

## 2. 왜 `cp` 로 하면 안 되는가

DB 는 WAL 모드다 (`PRAGMA journal_mode=wal`). 실행 중에 `cp` 하면 `.db` 와 `-wal` 이
**서로 다른 시점**의 것이 되어 복원할 때 깨진다. 파일 크기도 개수도 멀쩡해 보이므로
**복구를 시도하는 순간에야** 알게 된다.

`state_backup.py` 는 sqlite 온라인 백업 API(`Connection.backup()`)를 쓴다. 원본이
쓰이는 중에도 일관된 스냅샷을 만들고, 만든 다음 `PRAGMA integrity_check` 와 체크섬으로
**검증한다.** 백업은 "만들었다"가 아니라 "복원 가능하다"가 성공이다.

## 3. 운영

```bash
# 자동: 매일 04:00 (STATE_BACKUP_HOUR/MINUTE), 최근 7개 보관
make backup              # 수동 실행
make backup-verify       # 최신 아카이브가 복원 가능한지 확인
make backup-drill        # 복구 리허설 — 임시 경로에 실제로 풀어서 대조
curl -s localhost:8100/ops/backups | jq    # 현황 + 최신본 검증 결과
```

설정은 `.env` — `STATE_BACKUP_ENABLED` / `STATE_BACKUP_DIR` / `STATE_BACKUP_KEEP`.

### 반드시 다른 노드로 옮길 것

기본 경로(`/home/ubuntu/stock_auto_backups`)는 **같은 디스크**다. 디스크가 죽으면
백업도 같이 죽는다 — 그건 SPOF 대비가 아니다.

```bash
# macstudio 로 주기 복사 (키 인증 설정돼 있음)
rsync -av --delete /home/ubuntu/stock_auto_backups/ macstudio:~/stock_auto_backups/
```

## 4. 복구 절차

복구는 **되돌릴 수 없다.** 현재 상태를 먼저 백업하고 시작한다.

```bash
# 0) 지금 상태를 먼저 보존 (복구가 틀렸을 때 돌아올 지점)
make backup

# 1) 서비스 정지 — 쓰는 중에 갈아끼우면 안 된다
docker compose --profile dev down

# 2) 아카이브 검증 (풀기 전에)
python3 -c "
import sys; sys.path.insert(0,'chart_agent_service')
from state_backup import verify_backup
import json; print(json.dumps(verify_backup('$ARCHIVE'), ensure_ascii=False, indent=2))"
#    status 가 'ok' 가 아니면 그 아카이브는 쓰지 않는다

# 3) 풀기
mkdir -p /tmp/restore && tar -xzf "$ARCHIVE" -C /tmp/restore

# 4) 현재 파일 치우기 (삭제하지 말고 옆으로)
mv chart_agent_service/output/scan_log.db{,.before-restore}
#    -wal / -shm 도 함께 치운다. 남아 있으면 복원본과 섞인다
rm -f chart_agent_service/output/scan_log.db-wal chart_agent_service/output/scan_log.db-shm

# 5) 복사
cp /tmp/restore/state/output/*.db chart_agent_service/output/
cp /tmp/restore/state/output/paper_trading_state.json chart_agent_service/output/
cp /tmp/restore/state/data/*.db chart_agent_service/data/
cp /tmp/restore/state/stock_analyzer/watchlist.txt stock_analyzer/

# 6) 기동 + 확인
docker compose --profile dev up -d
curl -s localhost:8100/health | jq
curl -s 'localhost:8100/signal-accuracy' | jq '.sampling'
#    manifest.json 의 row_counts 와 대조한다 — 숫자가 맞아야 복구된 것이다
```

### 새 노드에 처음부터 세우는 경우

1. 리포지토리 clone
2. `.env` 준비 — **백업에 없다면 키를 다시 발급/입력해야 한다** (`.env.example` 참고)
3. `docker compose --profile dev build`
4. 위 복구 절차 4~6
5. 토스 OpenAPI 는 **IP allowlist** 가 있다 — 새 노드 IP 를 등록해야 주문·시세가 된다

## 5. 이 절차의 한계 (알고 쓸 것)

- **테스트되지 않은 복구는 백업이 아니다.** `scripts/restore_drill.py` 가 운영 파일을
  건드리지 않고 복원을 실제로 해 본다 (`make backup-drill`).

  | 일시 | 아카이브 | 결과 |
  |---|---|---|
  | 2026-09-14 08:32 | `stock_auto_state_20260914_083210.tar.gz` (2.83 MB) | **성공** — DB 5개 integrity ok, scan_log 70,840 / signal_outcomes 5,442 / app_state 8 행 일치, 파일 2개 크기 일치 |

  다만 리허설은 **복원본이 온전한지**까지만 본다. 서비스를 실제로 정지하고 갈아끼우는
  §4 절차 전체를 돌려본 적은 아직 없다.
- 백업 주기는 24시간이다. 최악의 경우 하루치 스캔·평가가 사라진다
- `.env` 를 백업에 넣지 않으면 키는 별도로 보관해야 한다. 어디에 두는지 정하는 것도
  복구 절차의 일부다 — 지금은 정해져 있지 않다
- 같은 노드에만 두면 아무 것도 대비되지 않는다 (§3 참조)
