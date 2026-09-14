"""두 패키지 사이의 모듈 이름 충돌을 막는다.

`stock_analyzer/` 와 `chart_agent_service/` 는 **둘 다 sys.path 에 들어간다**
(안티패턴 #5, 양방향 주입). 그래서 같은 파일명이 양쪽에 있으면 **어느 쪽이 잡힐지는
import 순서가 정한다.**

2026-09-14 실제 피해 (#64 에서 로깅을 켠 뒤 드러남):

  `stock_analyzer/news_analyzer.py` 가 `chart_agent_service/news_analyzer.py` 를 가렸다.
  webui 컨테이너에서는 stock_analyzer 가 앞서므로 늘 이쪽이 잡혔고:

    local_engine._DIRECT_NEWS = False
      → 뉴스는 항상 HTTP 폴백. in-proc 경로는 한 번도 쓰인 적이 없다
    GeopoliticalAnalyst._fetch_news_context
      → {'error': "cannot import name 'fetch_news_with_sentiment' ..."}
      → _context_available False → **뉴스 없이 지정학 분석을 했다**

  agent-api 에서는 service.py 가 먼저 import 해 sys.modules 에 올려둔 덕에 우연히
  올바른 모듈이 잡혔다. 즉 **운으로 돌아가고 있었다.**

기존 테스트 3개(`test_agent_groups`, `test_price_source_verification`,
`test_signal_outcome_recording`)가 이미 "stock_analyzer 를 앞에 넣으면 동명 모듈이
잘못 로드된다"는 주석을 달고 sys.path 순서를 조심하고 있었다 — 증상은 알려져
있었지만 원인을 없애지 않았다.
"""

import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
_ANALYZER = os.path.join(_ROOT, "stock_analyzer")
_AGENT = os.path.join(_ROOT, "chart_agent_service")


def _top_level_modules(directory: str) -> set[str]:
    return {
        name[:-3]
        for name in os.listdir(directory)
        if name.endswith(".py") and not name.startswith("__")
    }


def test_no_module_name_collisions_between_packages():
    """이름이 겹치면 import 순서가 동작을 정한다 — 그건 버그의 온상이다."""
    collisions = _top_level_modules(_ANALYZER) & _top_level_modules(_AGENT)

    assert not collisions, (
        f"동명 모듈: {sorted(collisions)} — 두 디렉토리가 모두 sys.path 에 들어가므로 "
        "어느 쪽이 잡힐지 import 순서가 정한다. 한쪽 이름을 바꿔라."
    )


def test_news_analyzer_resolves_to_the_agent_implementation():
    """webui 쪽이 앞서도 fetch_news_with_sentiment 가 있어야 한다."""
    for path in (_ANALYZER, _AGENT):
        if path in sys.path:
            sys.path.remove(path)
    sys.path.insert(0, _AGENT)
    sys.path.insert(0, _ANALYZER)      # webui 컨테이너와 같은 순서
    sys.modules.pop("news_analyzer", None)

    import news_analyzer

    assert hasattr(news_analyzer, "fetch_news_with_sentiment")
    assert hasattr(news_analyzer, "get_news_cache_status")
    assert os.path.realpath(news_analyzer.__file__).startswith(os.path.realpath(_AGENT))


def test_legacy_module_is_still_importable_under_its_new_name():
    """지운 게 아니라 이름만 바꿨다 — 되살릴 여지를 남긴다."""
    if _ANALYZER not in sys.path:
        sys.path.insert(0, _ANALYZER)

    import legacy_news_analyzer

    assert hasattr(legacy_news_analyzer, "NewsAnalyzer")
    assert "가리고 있었다" in (legacy_news_analyzer.__doc__ or ""), "경위 기록이 없다"


def test_nothing_imports_the_legacy_module_by_the_old_name():
    """`from news_analyzer import NewsAnalyzer` 같은 잔재가 없어야 한다."""
    import glob
    import re

    offenders = []
    scanned = [
        path
        for directory in (_ANALYZER, _AGENT)
        for path in glob.glob(os.path.join(directory, "**", "*.py"), recursive=True)
    ]
    for path in scanned:
        if "legacy_news_analyzer.py" in path:
            continue
        # 우리 소스만 본다 — .venv 안에는 utf-8 이 아닌 테스트 픽스처가 있다
        src = open(path, encoding="utf-8").read()
        if re.search(r"from news_analyzer import .*\b(NewsAnalyzer|IntegratedAnalyzer)\b", src):
            offenders.append(os.path.relpath(path, _ROOT))

    assert not offenders, f"옛 이름으로 레거시 클래스를 import 하는 곳: {offenders}"


@pytest.mark.parametrize("directory", [_ANALYZER, _AGENT])
def test_non_package_subdirs_do_not_shadow_top_level_modules(directory):
    """sys.path 에 들어갈 수 있는 하위 디렉토리만 본다.

    `__init__.py` 가 있는 패키지는 `ui.pages.multi_agent` 처럼 경로로 구분되므로
    최상위 `multi_agent` 를 가리지 않는다. 위험한 것은 **패키지가 아닌** 디렉토리가
    sys.path 에 추가되는 경우다 — 그때만 같은 이름이 충돌한다.
    """
    top = _top_level_modules(directory)
    offenders = {}
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        if root == directory or os.path.exists(os.path.join(root, "__init__.py")):
            continue
        overlap = {f[:-3] for f in files if f.endswith(".py")} & top
        if overlap:
            offenders[os.path.relpath(root, _ROOT)] = sorted(overlap)

    assert not offenders, f"패키지가 아닌 디렉토리의 동명 모듈: {offenders}"
