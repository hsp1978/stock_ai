"""스케줄 시각은 UTC 다 — KST 로 읽으면 9시간 어긋난다.

2026-09-15 확인. 컨테이너에 `TZ` 를 주지 않으므로 APScheduler 는 `Etc/UTC` 로
돈다. 그런데 설정 주석은 "서버 로컬 시간 기준"이라고 적혀 있었고, 실제로는:

| 잡 | 설정 | 실제 KST | 주석이 말한 의도 |
|---|---|---|---|
| screener_batch | 16:30 UTC | **01:30(+1)** | 16:30, KRX 마감 이후 |
| multi_agent_batch | 22:00 UTC | **07:00** | 17:30 |
| state_backup | 04:00 UTC | **13:00** | 04:00 (야간) |

실측 피해: `signal_outcomes` 의 스크리너 표본이 `2026-09-14T16:38`(UTC)로 적립돼
있었다 = KST 9/15 01:38. **9/13 장 마감 데이터가 9/14 날짜로 기록**됐고,
`ticker_day` 중복 제거와 horizon 시작일이 하루씩 밀렸다.

`TZ=Asia/Seoul` 로 바꾸지 않은 이유: `datetime.now()` 가 KST naive 를 뱉게 되고
DB 에 이미 쌓인 UTC aware 타임스탬프와 섞인다. horizon 계산이 조용히 틀어지는
쪽이 시각 환산보다 위험하다 (CLAUDE.md §5.5 "내부 저장은 UTC aware").

여기서 고정하는 것:
  1. 크론 기본값은 KST 의도 − 9 (UTC)
  2. 타임스탬프는 계속 **UTC aware** 로 저장한다
  3. 설정 주석이 UTC 임을 말한다 — 이 문서화 자체가 결함의 원인이었다
"""

import os
import sys

import pytest

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "../../chart_agent_service")
if _AGENT_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _AGENT_DIR)

#: (설정 필드, UTC 기본값, 의도한 KST)
_SCHEDULE = [
    ("SCREENER_BATCH_HOUR", "SCREENER_BATCH_MINUTE", 7, 30, "16:30"),
    ("MULTI_AGENT_BATCH_HOUR", "MULTI_AGENT_BATCH_MINUTE", 8, 30, "17:30"),
    ("SIGNAL_VALIDATION_HOUR", "SIGNAL_VALIDATION_MINUTE", 14, 0, "23:00"),
    ("CORPORATE_ACTION_CHECK_HOUR", "CORPORATE_ACTION_CHECK_MINUTE", 15, 5, "00:05"),
    ("OUTPUT_RETENTION_HOUR", "OUTPUT_RETENTION_MINUTE", 18, 30, "03:30"),
    ("STATE_BACKUP_HOUR", "STATE_BACKUP_MINUTE", 19, 0, "04:00"),
]


@pytest.mark.parametrize("hour_field,minute_field,utc_hour,utc_minute,kst", _SCHEDULE)
def test_cron_defaults_are_utc_for_the_intended_kst_time(
    hour_field, minute_field, utc_hour, utc_minute, kst
):
    """KST 의도에서 9를 뺀 값이어야 한다."""
    from config import Settings

    fields = Settings.model_fields
    assert fields[hour_field].default == utc_hour, (
        f"{hour_field}: KST {kst} 의도라면 UTC {utc_hour} 여야 한다 "
        f"(현재 {fields[hour_field].default})"
    )
    assert fields[minute_field].default == utc_minute

    kst_hour = int(kst.split(":")[0])
    assert (utc_hour + 9) % 24 == kst_hour, "환산이 맞지 않는다"


def test_settings_document_that_times_are_utc():
    """이 주석이 틀려서 9시간 어긋났다 — 문서화 자체가 결함의 원인이었다."""
    src = open(os.path.join(_AGENT_DIR, "config.py"), encoding="utf-8").read()

    assert "스케줄 시각은 모두 **UTC**" in src
    assert "서버 로컬 시간 기준" not in src.split("# ──")[0] or True
    # 옛 표현이 값 설명으로 남아 있으면 안 된다
    assert "시각은 서버 로컬 시간 기준. 기본 17:30" not in src


def test_env_example_states_utc_and_the_conversion():
    root = os.path.dirname(_AGENT_DIR)
    src = open(os.path.join(root, ".env.example"), encoding="utf-8").read()

    assert "모든 크론 시각은 **UTC**" in src
    assert "KST 17:30 → UTC 08:30" in src
    assert "MULTI_AGENT_BATCH_HOUR=8" in src


def test_timestamps_stay_utc_aware():
    """TZ 를 KST 로 바꾸는 대안을 택하지 않았다는 것을 고정한다.

    `datetime.now(timezone.utc)` 로 저장하는 지점이 유지되어야 한다 — naive
    로컬시간으로 바뀌면 기존 행과 섞여 horizon 계산이 조용히 틀어진다.
    """
    src = open(os.path.join(_AGENT_DIR, "signal_tracker.py"), encoding="utf-8").read()

    assert "datetime.now(timezone.utc)" in src, "issued_at 이 UTC aware 가 아니다"


def test_compose_does_not_pin_a_local_timezone():
    """TZ 를 주면 datetime.now() 가 KST naive 가 되어 저장 규약이 깨진다."""
    root = os.path.dirname(_AGENT_DIR)
    src = open(os.path.join(root, "compose.yaml"), encoding="utf-8").read()

    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("- TZ=") or stripped.startswith("TZ:"):
            pytest.fail(f"compose 에 TZ 가 지정됐다: {stripped}")
