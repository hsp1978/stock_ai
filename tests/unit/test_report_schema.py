"""리포트 출력 필드에 소비자가 있는지 강제한다.

`regime_weighted_score`(소비처 0곳)와 `close_thread_connection()`(호출부 0곳)이
같은 습관에서 나왔다 — 만들어 두고 연결하지 않는 것. 후자는 7일 만에 fd를
고갈시켜 API 전체를 죽였다.

이 테스트는 aggregate()가 내는 키를 소스에서 뽑아 레지스트리와 대조한다.
새 필드를 선언 없이 추가하면 실패한다.
"""

import ast
import os
import re
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
_ANALYZER_DIR = os.path.join(_ROOT, "stock_analyzer")
if _ANALYZER_DIR not in sys.path:  # noqa: E402
    sys.path.insert(0, _ANALYZER_DIR)

from report_schema import CONSUMER_GLOBS, REPORT_FIELDS  # noqa: E402


def _aggregate_result_keys() -> set[str]:
    """enhanced_decision_maker.aggregate() 안의 `result = {...}` 키를 뽑는다.

    런타임 호출은 외부 API·LLM에 의존하므로 소스에서 정적으로 추출한다.
    """
    src = open(
        os.path.join(_ANALYZER_DIR, "enhanced_decision_maker.py"), encoding="utf-8"
    ).read()
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "aggregate"):
            continue
        for stmt in ast.walk(node):
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id == "result"
                and isinstance(stmt.value, ast.Dict)
            ):
                return {
                    k.value
                    for k in stmt.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                }
    raise AssertionError("aggregate()에서 result 딕셔너리를 찾지 못했다")


def _consumer_sources() -> str:
    chunks = []
    for rel in CONSUMER_GLOBS:
        path = os.path.join(_ROOT, rel)
        if os.path.exists(path):
            chunks.append(open(path, encoding="utf-8").read())
    return "\n".join(chunks)


# enforce_report_invariants가 사후에 덧붙이는 키 (result 리터럴에는 없다)
_POST_ATTACHED = {"invariant_violations"}


def test_every_produced_field_is_declared():
    """선언 없이 필드를 추가하면 실패한다."""
    produced = _aggregate_result_keys()
    declared = set(REPORT_FIELDS)

    undeclared = produced - declared
    assert not undeclared, (
        f"report_schema.REPORT_FIELDS에 선언되지 않은 출력 필드: {sorted(undeclared)}. "
        "소비자가 있으면 _c(), 진단용이면 _d()에 사유와 함께 등록할 것."
    )


def test_no_stale_declarations():
    """더 이상 생산되지 않는 필드가 레지스트리에 남아있지 않아야 한다."""
    produced = _aggregate_result_keys() | _POST_ATTACHED
    stale = set(REPORT_FIELDS) - produced
    assert not stale, f"생산되지 않는데 선언만 남은 필드: {sorted(stale)}"


@pytest.mark.parametrize(
    "field",
    sorted(n for n, s in REPORT_FIELDS.items() if s.purpose == "consumed"),
)
def test_consumed_field_has_a_real_consumer(field):
    """`consumed`로 선언했으면 실제로 읽는 코드가 있어야 한다."""
    src = _consumer_sources()
    # "field" 또는 'field' 형태의 키 접근
    pattern = rf"""["']{re.escape(field)}["']"""
    assert re.search(pattern, src), (
        f"'{field}'는 consumed로 선언됐지만 소비자 모듈에서 읽는 곳이 없다. "
        "연결하거나 _d()로 사유와 함께 강등할 것."
    )


def test_diagnostic_fields_state_why():
    """진단용 강등에는 사유가 필요하다 — 빈 사유는 그냥 방치다."""
    for name, spec in REPORT_FIELDS.items():
        if spec.purpose == "diagnostic":
            assert len(spec.note.strip()) >= 20, (
                f"'{name}'의 diagnostic 사유가 부실하다: {spec.note!r}"
            )


def test_registry_covers_known_dead_fields():
    """2026-08 감사에서 소비처 0으로 확인된 필드들이 진단용으로 명시됐는지."""
    for name in (
        "regime_weighted_score",
        "reflect_flags",
        "technical_analysis",
        "quant_analysis",
        "tool_agent_verdicts",
    ):
        assert REPORT_FIELDS[name].purpose == "diagnostic", (
            f"'{name}'은 소비처가 없다 — consumed로 두면 착시가 유지된다"
        )
