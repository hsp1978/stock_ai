#!/usr/bin/env bash
# 백업을 다른 노드로 복제한다 — **호스트에서** 실행한다.
#
# 왜 컨테이너가 아니라 호스트인가:
#   원격 복제에는 SSH 개인키가 필요하다. 네트워크에 노출된 서비스 컨테이너
#   (agent-api)에 키를 마운트하면 백업으로 얻는 것보다 잃는 게 크다. 그래서
#   agent-api 는 **로컬·마운트 경로**만 복제하고(순수 Python), 원격은 여기서 한다.
#
# 사용:
#   scripts/offsite_sync.sh                       # .env 의 OFFSITE_BACKUP_DEST 사용
#   scripts/offsite_sync.sh user@host:~/backups   # 목적지 직접 지정
#
# cron 예시 (매일 04:30 — state_backup 04:00 직후):
#   30 4 * * * scripts/offsite_sync.sh >> /var/log/offsite_sync.log 2>&1
#
# rsync 종료코드 0 은 '전송 끝'이지 '반대편이 온전함'이 아니다. 최신 아카이브의
# sha256 을 목적지에서 다시 계산해 대조한다 — 불일치면 실패로 끝낸다.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# .env 는 값에 공백·특수문자가 있을 수 있어 source 하지 않고 필요한 키만 읽는다
read_env() {
    local key="$1"
    [ -f .env ] || return 0
    grep -E "^${key}=" .env | tail -1 | cut -d= -f2- | tr -d '"'"'"'' || true
}

SOURCE_DIR="${STATE_BACKUP_DIR:-$(read_env STATE_BACKUP_DIR)}"
SOURCE_DIR="${SOURCE_DIR:-/home/ubuntu/stock_auto_backups}"
DEST="${1:-${OFFSITE_BACKUP_DEST:-$(read_env OFFSITE_BACKUP_DEST)}}"

if [ -z "$DEST" ]; then
    echo "[offsite] 목적지 미설정 — OFFSITE_BACKUP_DEST 를 정하거나 인자로 넘겨라." >&2
    echo "[offsite] 설정 전까지 백업은 이 노드에만 있다 (SPOF 미해소)." >&2
    exit 2
fi

if [ ! -d "$SOURCE_DIR" ]; then
    echo "[offsite] 백업 디렉토리 없음: $SOURCE_DIR" >&2
    exit 1
fi

LATEST="$(ls -1t "$SOURCE_DIR"/stock_auto_state_*.tar.gz 2>/dev/null | head -1 || true)"
if [ -z "$LATEST" ]; then
    echo "[offsite] 복제할 아카이브 없음: $SOURCE_DIR" >&2
    exit 1
fi

echo "[offsite] $SOURCE_DIR → $DEST"
rsync -a --delete \
    -e "ssh -o BatchMode=yes -o ConnectTimeout=10" \
    "$SOURCE_DIR/" "$DEST/"

# ── 도착 검증 ──
NAME="$(basename "$LATEST")"
LOCAL_SHA="$(sha256sum "$LATEST" | awk '{print $1}')"

case "$DEST" in
    *:*)   # 원격
        TARGET="${DEST%%:*}"
        RPATH="${DEST#*:}"
        REMOTE_SHA="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$TARGET" \
            "sha256sum '$RPATH/$NAME' 2>/dev/null || shasum -a 256 '$RPATH/$NAME'" \
            | awk '{print $1}')"
        ;;
    *)     # 로컬 경로
        REMOTE_SHA="$(sha256sum "$DEST/$NAME" | awk '{print $1}')"
        ;;
esac

if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
    echo "[offsite] 체크섬 불일치 — 사본이 온전하지 않다 ($NAME)" >&2
    echo "[offsite]   원본 $LOCAL_SHA" >&2
    echo "[offsite]   목적 ${REMOTE_SHA:-<확인 실패>}" >&2
    exit 1
fi

echo "[offsite] 완료 — $NAME 체크섬 일치"
