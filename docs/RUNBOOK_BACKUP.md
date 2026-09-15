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

### 반드시 원본과 다른 디스크로 옮길 것

기본 경로(`/home/ubuntu/stock_auto_backups`)는 운영 데이터와 **같은 디스크**다
(`nvme0n1`). 디스크가 죽으면 백업도 같이 죽는다 — 그건 SPOF 대비가 아니다.

목적지는 **운영자가 정한다** (`OFFSITE_BACKUP_DEST`). 비어 있으면 아무 데도 보내지
않고 `/ops/backups` 가 `configured: false` 로 보고한다 — '설정 안 됨'을 성공으로
덮지 않는다.

| 형태 | 예 | 실행 주체 |
|---|---|---|
| 로컬·마운트 | `/db4/stock_auto_backups` | **agent-api 가 직접** (매 백업 후, 순수 Python) |
| 원격 SSH | `user@host:~/stock_auto_backups` | **호스트** `scripts/offsite_sync.sh` (cron) |

원격을 컨테이너에서 하지 않는 이유: SSH 개인키가 필요한데, 네트워크에 노출된 서비스
컨테이너에 키를 마운트하면 백업으로 얻는 것보다 잃는 게 크다. agent-api 에는 `rsync`·
`ssh` 를 넣지 않았고, 원격 목적지가 컨테이너에서 시도되면 **어디서 돌려야 하는지**를
담은 에러로 끝난다.

```bash
# 원격을 쓸 때 — 호스트 cron (state_backup 04:00 직후)
30 4 * * * /home/ubuntu/stock_auto/scripts/offsite_sync.sh >> /var/log/offsite_sync.log 2>&1
```

**복사했다 ≠ 도착했다.** `rsync` 종료코드 0 은 전송이 끝났다는 뜻이지 반대편 파일이
온전하다는 뜻이 아니다. 양쪽 경로 모두 복제 후 최신 아카이브의 sha256 을 목적지에서
다시 계산해 대조하고, 불일치·확인 불가면 `degraded` 로 보고하고 알린다.

#### 현재 설정 (2026-09-14)

```
OFFSITE_BACKUP_DEST=/db4/stock_auto_backups
```

`/db4` 는 `sda`(1.8T)로 **운영 데이터가 있는 `nvme0n1` 과 다른 물리 디스크**다.

```bash
df --output=source /home/ubuntu/stock_auto_backups   # /dev/mapper/ubuntu--vg-ubuntu--lv
df --output=source /db4/stock_auto_backups           # /dev/sda          ← 달라야 한다
```

**경로를 바꿀 때는 반드시 이걸 확인할 것.** 같은 디스크 안의 다른 경로로 바꾸면 마운트도
복제도 성공하고 `/ops/backups` 도 `configured: true` 로 보이지만, **대비는 사라진다.**

| | |
|---|---|
| ✅ NVMe(`nvme0n1`) 고장 | 백업이 `sda` 에 살아남는다 |
| ✅ 실수로 지운 경우 | 사본이 남는다 |
| ❌ **머신 자체 손실** (화재·도난·메인보드) | 두 디스크가 같은 기계 안에 있다 |

머신 손실까지 대비하려면 다른 노드가 필요하다. 후보 (2026-09-14 확인):

| 노드 | 상태 |
|---|---|
| `hsptest-macstudio` (문서상 듀얼 노드 파트너) | **5일째 offline** — `is_mac_studio_available()` False |
| `testmacstudio2-macstudio` (100.83.234.49) | SSH 포트 응답 |
| `parkhongnas` (100.81.207.58) | SSH 응답. 단 `ubuntu` + `id_ed25519` 로는 거부 — 계정·키 배포 필요 |

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
  | 2026-09-14 09:23 | `stock_auto_state_20260914_092321.tar.gz` — **`/db4` 오프사이트 사본으로** | **성공** — DB 5개 integrity ok, scan_log 70,864 / signal_outcomes 5,446 행 일치 (운영과 차이 0) |

  다만 리허설은 **복원본이 온전한지**까지만 본다. 서비스를 실제로 정지하고 갈아끼우는
  §4 절차 전체를 돌려본 적은 아직 없다.
- 백업 주기는 24시간이다. 최악의 경우 하루치 스캔·평가가 사라진다
- `.env` 를 백업에 넣지 않으면 키는 별도로 보관해야 한다. 어디에 두는지 정하는 것도
  복구 절차의 일부다 — 지금은 정해져 있지 않다
- 오프사이트 사본은 `/db4`(다른 물리 디스크)에 있다. **같은 기계 안이다** — 디스크
  고장은 대비되지만 머신 손실은 아니다. 다른 노드 복제는 아직 없다 (§3)
- 문서상 듀얼 노드 파트너인 `hsptest-macstudio` 가 **5일째 offline** 이다
  (2026-09-14 확인, `is_mac_studio_available()` False). 목적지를 정할 때 함께 볼 것
