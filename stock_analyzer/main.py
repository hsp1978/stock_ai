#!/usr/bin/env python3
"""
미국 주식 AI 분석 시스템 - 메인 실행 파일
Usage:
    python main.py AAPL                          # 기본 분석
    python main.py AAPL --ai gpt4o               # GPT-4o 멀티모달 분석
    python main.py AAPL --ai ollama              # Ollama 로컬 LLM 분석
    python main.py AAPL --account 50000          # 계좌 크기 지정
    python main.py AAPL --telegram               # 텔레그램으로 리포트 전송
    python main.py AAPL --ai gpt4o --telegram    # AI 분석 + 텔레그램 전송
    python main.py --bot                         # 텔레그램 봇 모드 (대화형)
    python main.py --watchlist                   # watchlist.txt 종목 일괄 분석
    python main.py --watchlist mylist.txt        # 지정 파일로 일괄 분석
    python main.py AAPL --agent                  # 12개 기법 에이전트 분석 (LLM 없이)
    python main.py AAPL --agent --ai ollama      # 에이전트 + LLM 종합 판단
    python main.py AAPL --agent --ai gpt4o --telegram  # 에이전트 + GPT-4o + 텔레그램
"""
import argparse
import json
import sys
import os
import time
from datetime import datetime

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import OUTPUT_DIR, ACCOUNT_SIZE
from core.data_collector import DataCollector
from core.indicators import TechnicalIndicators
from risk.risk_manager import RiskManager
from visualization.chart_generator import ChartGenerator
from analysis.ai_analyzer import AIAnalyzer
from analysis.chart_agent import ChartAnalysisAgent, generate_agent_chart
from notification.telegram_bot import TelegramBot


def run_analysis(
    ticker: str,
    ai_mode: str = "none",
    account_size: float = ACCOUNT_SIZE,
    send_telegram: bool = False,
    use_agent: bool = False,
):
    """단일 종목 종합 분석 실행"""

    print(f"\n{'='*60}")
    print(f"  {ticker} 종합 분석 시작 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # ── 1. 데이터 수집 ───────────────────────────────────────

    print("[1/7] 데이터 수집 중...")
    collector = DataCollector(ticker)

    try:
        ohlcv = collector.get_ohlcv()
        print(f"  ✓ OHLCV: {len(ohlcv)}일 데이터 수집 완료")
    except ValueError as e:
        print(f"  ✗ {e}")
        if send_telegram:
            bot = TelegramBot()
            bot.send_message(f"❌ <b>{ticker}</b> 분석 실패: {e}")
        return None

    fundamentals = collector.get_fundamentals()
    print(f"  ✓ 펀더멘털: {fundamentals.get('company_name', ticker)}")

    options_data = collector.get_options_summary()
    if options_data:
        print(f"  ✓ 옵션: P/C Ratio(Vol)={options_data.get('put_call_ratio_volume', 'N/A')}")
    else:
        print(f"  - 옵션 데이터 없음")

    macro_data = DataCollector.get_macro_data()
    if macro_data:
        print(f"  ✓ 거시경제: {len(macro_data)}개 지표 수집")
    else:
        print(f"  - 거시경제 데이터 없음 (FRED API 키 필요)")

    insiders = collector.get_insider_trades()
    if insiders:
        print(f"  ✓ 내부자 거래: 최근 {len(insiders)}건")

    # ── 2. 기술 지표 계산 ────────────────────────────────────

    print("\n[2/7] 기술 지표 계산 중...")
    ti = TechnicalIndicators(ohlcv)
    df_indicators = ti.calculate_all()
    indicators_summary = ti.get_latest_summary()
    print(f"  ✓ 현재가: ${indicators_summary['price']['close']}")
    print(f"  ✓ RSI: {indicators_summary['momentum'].get('RSI', 'N/A')}")
    print(f"  ✓ 추세 강도: {indicators_summary['trend'].get('trend_strength', 'N/A')}")

    # ── 3. 리스크 분석 ───────────────────────────────────────

    print("\n[3/7] 리스크 분석 중...")
    rm = RiskManager(account_size=account_size)
    current_price = indicators_summary['price']['close']
    atr = indicators_summary['volatility'].get('ATR', current_price * 0.02)

    risk_report = rm.generate_risk_report(current_price, atr, direction="long")
    stops = risk_report['stops']
    position = risk_report['position']

    print(f"  ✓ 손절가: ${stops['stop_loss']} ({stops['stop_distance_pct']}%)")
    print(f"  ✓ 익절가: ${stops['take_profit']} ({stops['target_distance_pct']}%)")
    print(f"  ✓ 권장 수량: {position['shares']}주 (${position['position_value']})")

    for w in risk_report.get('warnings', []):
        print(f"  ⚠ {w}")

    # ── 4. 차트 생성 ─────────────────────────────────────────

    print("\n[4/7] 분석 차트 생성 중...")
    chart_path = None
    try:
        cg = ChartGenerator(ticker, df_indicators)
        chart_path = cg.generate_analysis_chart()
        print(f"  ✓ 차트 저장: {chart_path}")
    except Exception as e:
        print(f"  ✗ 차트 생성 실패: {e}")

    # ── 5. AI 분석 (선택적) ──────────────────────────────────

    ai_result = None
    if ai_mode != "none":
        print(f"\n[5/7] AI 분석 중 ({ai_mode})...")
        analyzer = AIAnalyzer()

        if ai_mode == "gpt4o":
            ai_result = analyzer.analyze_with_gpt4o(
                ticker, indicators_summary, fundamentals,
                risk_report, chart_path, macro_data, options_data
            )
        elif ai_mode == "ollama":
            ai_result = analyzer.analyze_with_ollama(
                ticker, indicators_summary, fundamentals,
                risk_report, macro_data, options_data
            )

        if ai_result:
            print(f"  ✓ AI 분석 완료 ({len(ai_result)}자)")
    else:
        print(f"\n[5/7] AI 분석 건너뜀 (--ai 옵션으로 활성화)")

    # ── 5.5 에이전트 분석 (선택적) ───────────────────────────

    agent_result = None
    agent_chart_path = None
    if use_agent:
        print(f"\n[5.5/7] 에이전트 분석 중 (12개 기법)...")
        agent = ChartAnalysisAgent(ticker, df_indicators)

        if ai_mode != "none":
            agent_result = agent.run(mode=ai_mode)
        else:
            agent_result = agent.run(mode="none")  # LLM 없이 전수 분석

        print(f"  ✓ 최종 신호: {agent_result.get('final_signal', '?')}")
        print(f"  ✓ 종합 점수: {agent_result.get('composite_score', 0)}")
        print(f"  ✓ 신뢰도: {agent_result.get('confidence', 0)}")

        # 에이전트 차트 생성
        try:
            agent_chart_path = generate_agent_chart(ticker, df_indicators, agent_result)
            if agent_chart_path:
                print(f"  ✓ 에이전트 차트: {agent_chart_path}")
        except Exception as e:
            print(f"  ✗ 에이전트 차트 생성 실패: {e}")

        # 에이전트 JSON 저장
        agent_json_path = os.path.join(OUTPUT_DIR, f"{ticker}_agent_{datetime.now().strftime('%Y%m%d')}.json")
        with open(agent_json_path, 'w', encoding='utf-8') as f:
            json.dump(agent_result, f, indent=2, ensure_ascii=False, default=str)
        print(f"  ✓ 에이전트 JSON: {agent_json_path}")

        # 에이전트 리포트 저장
        agent_txt_path = os.path.join(OUTPUT_DIR, f"{ticker}_agent_{datetime.now().strftime('%Y%m%d')}.txt")
        with open(agent_txt_path, 'w', encoding='utf-8') as f:
            f.write(f"{'='*60}\n")
            f.write(f"  {ticker} 에이전트 분석 리포트\n")
            f.write(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"{'='*60}\n\n")
            f.write(f"[최종 신호] {agent_result.get('final_signal', '?')}\n")
            f.write(f"[종합 점수] {agent_result.get('composite_score', 0)} / 10\n")
            f.write(f"[신뢰도] {agent_result.get('confidence', 0)} / 10\n")
            f.write(f"[사용 도구] {agent_result.get('tool_count', 0)}개\n\n")
            f.write("── 도구별 결과 ──\n")
            for s in agent_result.get('tool_summaries', []):
                f.write(f"  {s['name']}: {s['signal']} ({s['score']:+.1f}) - {s['detail']}\n")
            if agent_result.get('llm_conclusion'):
                f.write(f"\n── LLM 종합 판단 ──\n")
                f.write(agent_result['llm_conclusion'])
                f.write("\n")
        print(f"  ✓ 에이전트 리포트: {agent_txt_path}")

        # LLM 종합 판단 콘솔 출력
        if agent_result.get('llm_conclusion'):
            print(f"\n{'='*60}")
            print(f"  에이전트 LLM 종합 판단")
            print(f"{'='*60}\n")
            print(agent_result['llm_conclusion'])
    else:
        print(f"\n[5.5/7] 에이전트 분석 건너뜀 (--agent 옵션으로 활성화)")

    # ── 6. 리포트 저장 ───────────────────────────────────────

    print(f"\n[6/7] 리포트 저장 중...")
    report = {
        "ticker": ticker,
        "analysis_date": datetime.now().isoformat(),
        "account_size": account_size,
        "price_summary": indicators_summary['price'],
        "technical_indicators": indicators_summary,
        "fundamentals": {k: v for k, v in fundamentals.items() if v is not None},
        "risk_management": risk_report,
        "options_market": options_data,
        "macro_environment": macro_data,
        "insider_trades": insiders,
        "chart_image": chart_path,
    }

    if ai_result:
        report["ai_analysis"] = ai_result

    if agent_result:
        report["agent_analysis"] = {
            "final_signal": agent_result.get("final_signal"),
            "composite_score": agent_result.get("composite_score"),
            "confidence": agent_result.get("confidence"),
            "signal_distribution": agent_result.get("signal_distribution"),
            "tool_summaries": agent_result.get("tool_summaries"),
            "agent_chart": agent_chart_path,
        }
        if agent_result.get("llm_conclusion"):
            report["agent_analysis"]["llm_conclusion"] = agent_result["llm_conclusion"]

    # JSON 리포트 저장
    json_path = os.path.join(OUTPUT_DIR, f"{ticker}_report_{datetime.now().strftime('%Y%m%d')}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"  ✓ JSON 리포트: {json_path}")

    # 텍스트 리포트 저장
    txt_path = os.path.join(OUTPUT_DIR, f"{ticker}_report_{datetime.now().strftime('%Y%m%d')}.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f"{'='*60}\n")
        f.write(f"  {ticker} ({fundamentals.get('company_name', '')}) 분석 리포트\n")
        f.write(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"{'='*60}\n\n")

        f.write(f"[가격] ${current_price} ({indicators_summary['price']['change_pct']:+.2f}%)\n")
        f.write(f"[거래량] {indicators_summary['price']['volume']:,} "
                f"(평균 대비 {indicators_summary['price']['volume_vs_avg']:.1f}배)\n\n")

        f.write("── 기술 지표 ──\n")
        for k, v in indicators_summary['trend'].items():
            f.write(f"  {k}: {v}\n")
        for k, v in indicators_summary['momentum'].items():
            f.write(f"  {k}: {v}\n")
        for k, v in indicators_summary['volatility'].items():
            f.write(f"  {k}: {v}\n")

        f.write(f"\n── 리스크 관리 (계좌: ${account_size:,.0f}) ──\n")
        f.write(f"  손절가: ${stops['stop_loss']} ({stops['stop_distance_pct']}%)\n")
        f.write(f"  익절가: ${stops['take_profit']} ({stops['target_distance_pct']}%)\n")
        f.write(f"  R:R 비율: {stops['risk_reward_ratio']}\n")
        f.write(f"  권장 수량: {position['shares']}주\n")
        f.write(f"  포지션 금액: ${position['position_value']:,.2f} ({position['position_pct']}%)\n")
        f.write(f"  리스크 금액: ${position['risk_amount']:,.2f} ({position['risk_pct']}%)\n")

        if options_data:
            f.write(f"\n── 옵션 시장 ──\n")
            f.write(f"  P/C Ratio (거래량): {options_data.get('put_call_ratio_volume', 'N/A')}\n")
            f.write(f"  P/C Ratio (미결제): {options_data.get('put_call_ratio_oi', 'N/A')}\n")
            f.write(f"  ATM IV: {options_data.get('atm_implied_volatility', 'N/A')}\n")

        if ai_result:
            f.write(f"\n── AI 분석 결과 ──\n")
            f.write(ai_result)
            f.write("\n")

    print(f"  ✓ 텍스트 리포트: {txt_path}")

    # AI 분석 결과 콘솔 출력
    if ai_result:
        print(f"\n{'='*60}")
        print(f"  AI 분석 결과")
        print(f"{'='*60}\n")
        print(ai_result)

    # ── 7. 텔레그램 전송 ─────────────────────────────────────

    if send_telegram:
        print(f"\n[7/7] 텔레그램 전송 중...")
        bot = TelegramBot()
        if bot.is_configured:
            # 에이전트 결과를 ai_result에 병합
            combined_ai = ai_result or ""
            if agent_result:
                agent_summary = (
                    f"\n\n━━ 에이전트 분석 (12개 기법) ━━\n"
                    f"신호: {agent_result.get('final_signal', '?')} | "
                    f"점수: {agent_result.get('composite_score', 0)} | "
                    f"신뢰도: {agent_result.get('confidence', 0)}\n"
                )
                for s in agent_result.get('tool_summaries', []):
                    agent_summary += f"  {s['name']}: {s['signal']} ({s['score']:+.1f})\n"
                if agent_result.get('llm_conclusion'):
                    agent_summary += f"\n{agent_result['llm_conclusion']}"
                combined_ai = combined_ai + agent_summary if combined_ai else agent_summary

            success = bot.send_full_report(
                ticker=ticker,
                indicators=indicators_summary,
                fundamentals=fundamentals,
                risk_report=risk_report,
                chart_path=agent_chart_path or chart_path,
                options_data=options_data,
                macro_data=macro_data,
                ai_result=combined_ai if combined_ai else None,
                json_path=json_path,
            )
            if success:
                print(f"  ✓ 텔레그램 전송 완료")
            else:
                print(f"  ✗ 텔레그램 전송 일부 실패")
        else:
            print(f"  ✗ 텔레그램 미설정. .env 파일에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 확인.")
    else:
        print(f"\n[7/7] 텔레그램 전송 건너뜀 (--telegram 옵션으로 활성화)")

    print(f"\n{'='*60}")
    print(f"  분석 완료.")
    print(f"{'='*60}\n")

    return report


def run_bot_mode(ai_mode: str = "none", account_size: float = ACCOUNT_SIZE):
    """
    텔레그램 봇 모드 (대화형)
    사용자가 텔레그램에서 명령어를 보내면 분석 실행 후 결과를 회신

    명령어:
      /analyze AAPL       → AAPL 분석 실행 + 결과 전송
      /a NVDA             → /analyze 단축어
      /help               → 사용법 안내
      /watchlist           → 관심 종목 일괄 분석
    """
    bot = TelegramBot()
    if not bot.is_configured:
        print("[오류] 텔레그램 봇 설정이 필요합니다.")
        print("  .env 파일에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID를 설정하세요.")
        return

    print(f"\n{'='*60}")
    print(f"  텔레그램 봇 모드 시작")
    print(f"  AI 모드: {ai_mode} | 계좌: ${account_size:,.0f}")
    print(f"  Ctrl+C 로 종료")
    print(f"{'='*60}\n")

    bot.send_message(
        "🤖 <b>주식 분석 봇 시작</b>\n\n"
        "사용 가능한 명령어:\n"
        "  /analyze AAPL — 종목 분석\n"
        "  /a NVDA — 분석 (단축)\n"
        "  /watchlist AAPL,MSFT,NVDA — 일괄 분석\n"
        "  /help — 도움말"
    )

    offset = 0
    while True:
        try:
            updates = bot.get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))

                # 본인 chat_id만 허용 (보안)
                if chat_id != bot.chat_id:
                    continue

                if not text.startswith("/"):
                    continue

                parts = text.split()
                cmd = parts[0].lower().split("@")[0]  # @봇이름 제거
                args = parts[1:] if len(parts) > 1 else []

                if cmd in ("/analyze", "/a"):
                    if not args:
                        bot.send_message("⚠️ 티커를 입력하세요.\n예: /analyze AAPL")
                        continue
                    ticker = args[0].upper()
                    bot.send_message(f"⏳ <b>{ticker}</b> 분석 시작...")
                    try:
                        run_analysis(ticker, ai_mode, account_size, send_telegram=True)
                    except Exception as e:
                        bot.send_message(f"❌ <b>{ticker}</b> 분석 중 오류: {e}")

                elif cmd == "/watchlist":
                    if not args:
                        bot.send_message("⚠️ 종목을 입력하세요.\n예: /watchlist AAPL,MSFT,NVDA")
                        continue
                    tickers = [t.strip().upper() for t in ",".join(args).split(",") if t.strip()]
                    bot.send_message(f"⏳ {len(tickers)}개 종목 일괄 분석 시작: {', '.join(tickers)}")
                    for t in tickers:
                        try:
                            run_analysis(t, ai_mode, account_size, send_telegram=True)
                        except Exception as e:
                            bot.send_message(f"❌ <b>{t}</b> 오류: {e}")
                        time.sleep(2)
                    bot.send_message(f"✅ {len(tickers)}개 종목 분석 완료!")

                elif cmd == "/help":
                    bot.send_message(
                        "📖 <b>사용법</b>\n\n"
                        "<b>/analyze AAPL</b> — 단일 종목 분석\n"
                        "<b>/a NVDA</b> — 분석 (단축)\n"
                        "<b>/watchlist AAPL,MSFT,NVDA</b> — 일괄 분석\n"
                        "<b>/help</b> — 이 메시지\n\n"
                        f"⚙️ AI 모드: {ai_mode}\n"
                        f"💰 계좌 크기: ${account_size:,.0f}"
                    )
                else:
                    bot.send_message(f"❓ 알 수 없는 명령어: {cmd}\n/help 로 사용법을 확인하세요.")

            time.sleep(1)

        except KeyboardInterrupt:
            print("\n봇 종료.")
            bot.send_message("🔴 봇이 종료되었습니다.")
            break
        except Exception as e:
            print(f"  [봇 오류] {e}")
            time.sleep(5)


def run_watchlist_from_file(
    file_path: str,
    ai_mode: str = "none",
    account_size: float = ACCOUNT_SIZE,
    send_telegram: bool = False,
    use_agent: bool = False,
):
    """파일에서 종목 목록을 읽어 일괄 분석"""
    if not os.path.exists(file_path):
        print(f"[오류] 종목 파일 없음: {file_path}")
        return

    with open(file_path, 'r', encoding='utf-8') as f:
        tickers = [
            line.strip().upper()
            for line in f
            if line.strip() and not line.strip().startswith('#')
        ]

    if not tickers:
        print(f"[오류] 종목 파일에 유효한 종목 없음: {file_path}")
        return

    print(f"\n{'='*60}")
    print(f"  일괄 분석 시작 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  종목 파일: {file_path}")
    print(f"  종목 수: {len(tickers)}개 - {', '.join(tickers)}")
    print(f"  AI 모드: {ai_mode} | 계좌: ${account_size:,.0f}")
    print(f"{'='*60}\n")

    success, fail = 0, 0
    for i, ticker in enumerate(tickers, 1):
        print(f"\n[{i}/{len(tickers)}] {ticker}")
        try:
            run_analysis(ticker, ai_mode, account_size, send_telegram, use_agent)
            success += 1
        except Exception as e:
            print(f"  ✗ {ticker} 분석 실패: {e}")
            fail += 1
        if i < len(tickers):
            time.sleep(5)

    print(f"\n{'='*60}")
    print(f"  일괄 분석 완료: 성공 {success} / 실패 {fail} / 전체 {len(tickers)}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="미국 주식 AI 분석 시스템")
    parser.add_argument("ticker", nargs="?", default=None,
                        help="분석할 종목 티커 (예: AAPL, MSFT, NVDA)")
    parser.add_argument("--ai", choices=["none", "gpt4o", "ollama"],
                        default="none", help="AI 분석 모드 (기본: none)")
    parser.add_argument("--account", type=float, default=ACCOUNT_SIZE,
                        help=f"계좌 크기 USD (기본: ${ACCOUNT_SIZE:,})")
    parser.add_argument("--telegram", action="store_true",
                        help="분석 결과를 텔레그램으로 전송")
    parser.add_argument("--bot", action="store_true",
                        help="텔레그램 봇 모드 (대화형, 텔레그램에서 명령어로 분석 요청)")
    parser.add_argument("--watchlist", nargs="?", const="watchlist.txt", default=None,
                        help="종목 파일로 일괄 분석 (기본: watchlist.txt)")
    parser.add_argument("--agent", action="store_true",
                        help="12개 기법 차트 분석 에이전트 활성화 (--ai와 조합 가능)")

    args = parser.parse_args()

    if args.bot:
        run_bot_mode(args.ai, args.account)
    elif args.watchlist:
        # 상대 경로인 경우 스크립트 디렉토리 기준으로 변환
        wl_path = args.watchlist
        if not os.path.isabs(wl_path):
            wl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), wl_path)
        run_watchlist_from_file(wl_path, args.ai, args.account, args.telegram, args.agent)
    elif args.ticker:
        run_analysis(args.ticker, args.ai, args.account, args.telegram, args.agent)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
