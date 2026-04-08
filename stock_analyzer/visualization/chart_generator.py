"""
차트 생성 모듈
Plotly 기반 (기본) + matplotlib fallback
AI 멀티모달 분석용 이미지 생성
"""
import pandas as pd
import numpy as np
import os
from config.settings import (
    OUTPUT_DIR, CHART_HISTORY_DAYS,
    BOLLINGER_PERIOD, BOLLINGER_STD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL
)


class ChartGenerator:
    """AI 분석용 차트 이미지 생성기"""

    def __init__(self, ticker: str, df: pd.DataFrame):
        self.ticker = ticker
        self.df = df.tail(CHART_HISTORY_DAYS).copy()

    def generate_analysis_chart(self, save_path: str = None) -> str:
        """차트 생성. Plotly 실패 시 matplotlib fallback."""
        if save_path is None:
            save_path = os.path.join(OUTPUT_DIR, f"{self.ticker}_analysis.png")

        try:
            return self._generate_plotly(save_path)
        except Exception as e:
            print(f"  [정보] Plotly 차트 실패 ({e}). matplotlib fallback.")
            return self._generate_matplotlib(save_path)

    def _generate_plotly(self, save_path: str) -> str:
        """Plotly 기반 고품질 차트"""
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        fig = make_subplots(
            rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03,
            row_heights=[0.5, 0.15, 0.15, 0.2],
            subplot_titles=[f"{self.ticker} Price + BB", "Volume", "RSI (14)", "MACD"]
        )
        df = self.df

        fig.add_trace(go.Candlestick(
            x=df.index, open=df['Open'], high=df['High'],
            low=df['Low'], close=df['Close'], name='Price',
            increasing_line_color='#26a69a', decreasing_line_color='#ef5350',
        ), row=1, col=1)

        for ma, color in {'SMA_20': '#FFD700', 'SMA_50': '#FF8C00', 'SMA_200': '#FF1493'}.items():
            if ma in df.columns:
                fig.add_trace(go.Scatter(x=df.index, y=df[ma], name=ma,
                    line=dict(color=color, width=1)), row=1, col=1)

        bbu = f'BBU_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'
        bbl = f'BBL_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'
        if bbu in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df[bbu], name='BB Upper',
                line=dict(color='rgba(173,216,230,0.5)', width=1, dash='dash')), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df[bbl], name='BB Lower',
                line=dict(color='rgba(173,216,230,0.5)', width=1, dash='dash'),
                fill='tonexty', fillcolor='rgba(173,216,230,0.1)'), row=1, col=1)

        colors = ['#26a69a' if c >= o else '#ef5350' for c, o in zip(df['Close'], df['Open'])]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name='Volume',
            marker_color=colors, opacity=0.7), row=2, col=1)

        if 'RSI' in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], name='RSI',
                line=dict(color='#7B68EE', width=1.5)), row=3, col=1)
            fig.add_hline(y=70, line_dash="dash", line_color="red", line_width=0.8, row=3, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="green", line_width=0.8, row=3, col=1)

        macd_col = f'MACD_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
        macd_sig = f'MACDs_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
        macd_hist = f'MACDh_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
        if macd_col in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df[macd_col], name='MACD',
                line=dict(color='#00BFFF', width=1.5)), row=4, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df[macd_sig], name='Signal',
                line=dict(color='#FF6347', width=1.5)), row=4, col=1)
        if macd_hist in df.columns:
            hc = ['#26a69a' if v >= 0 else '#ef5350' for v in df[macd_hist]]
            fig.add_trace(go.Bar(x=df.index, y=df[macd_hist], name='Hist',
                marker_color=hc, opacity=0.6), row=4, col=1)

        fig.update_layout(title=f'{self.ticker} Technical Analysis',
            template='plotly_dark', height=1000, width=1400,
            showlegend=False, xaxis_rangeslider_visible=False,
            margin=dict(l=60, r=30, t=50, b=30))
        fig.update_yaxes(title_text="Price", row=1, col=1)
        fig.update_yaxes(title_text="Volume", row=2, col=1)
        fig.update_yaxes(title_text="RSI", row=3, col=1, range=[0, 100])
        fig.update_yaxes(title_text="MACD", row=4, col=1)

        fig.write_image(save_path, scale=2)
        return save_path

    def _generate_matplotlib(self, save_path: str) -> str:
        """matplotlib fallback (Chrome 불필요)"""
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib.patches import Rectangle

        df = self.df
        fig, axes = plt.subplots(4, 1, figsize=(14, 10), sharex=True,
            gridspec_kw={'height_ratios': [3, 1, 1, 1.2]})
        fig.patch.set_facecolor('#1e1e1e')

        for ax in axes:
            ax.set_facecolor('#1e1e1e')
            ax.tick_params(colors='white')
            ax.yaxis.label.set_color('white')
            for spine in ax.spines.values():
                spine.set_color('#444')

        # ── Row 1: 가격 + MA + BB ────────────────────────────
        ax1 = axes[0]
        ax1.plot(df.index, df['Close'], color='white', linewidth=1, label='Close')

        for ma, color in {'SMA_20': '#FFD700', 'SMA_50': '#FF8C00', 'SMA_200': '#FF1493'}.items():
            if ma in df.columns:
                ax1.plot(df.index, df[ma], color=color, linewidth=0.8, label=ma)

        bbu = f'BBU_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'
        bbl = f'BBL_{BOLLINGER_PERIOD}_{BOLLINGER_STD}'
        if bbu in df.columns:
            ax1.fill_between(df.index, df[bbu], df[bbl], alpha=0.1, color='cyan')
            ax1.plot(df.index, df[bbu], color='cyan', linewidth=0.5, alpha=0.5)
            ax1.plot(df.index, df[bbl], color='cyan', linewidth=0.5, alpha=0.5)

        ax1.set_title(f'{self.ticker} Technical Analysis', color='white', fontsize=14)
        ax1.legend(loc='upper left', fontsize=7, facecolor='#2e2e2e', edgecolor='#444',
                   labelcolor='white')
        ax1.set_ylabel('Price', color='white')

        # ── Row 2: Volume ────────────────────────────────────
        ax2 = axes[1]
        colors = ['#26a69a' if c >= o else '#ef5350' for c, o in zip(df['Close'], df['Open'])]
        ax2.bar(df.index, df['Volume'], color=colors, alpha=0.7, width=0.8)
        if 'Volume_SMA_20' in df.columns:
            ax2.plot(df.index, df['Volume_SMA_20'], color='yellow', linewidth=0.8)
        ax2.set_ylabel('Volume', color='white')

        # ── Row 3: RSI ───────────────────────────────────────
        ax3 = axes[2]
        if 'RSI' in df.columns:
            ax3.plot(df.index, df['RSI'], color='#7B68EE', linewidth=1.2)
            ax3.axhline(70, color='red', linestyle='--', linewidth=0.7)
            ax3.axhline(30, color='green', linestyle='--', linewidth=0.7)
            ax3.fill_between(df.index, 30, 70, alpha=0.05, color='gray')
            ax3.set_ylim(0, 100)
        ax3.set_ylabel('RSI', color='white')

        # ── Row 4: MACD ──────────────────────────────────────
        ax4 = axes[3]
        macd_col = f'MACD_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
        macd_sig = f'MACDs_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
        macd_hist = f'MACDh_{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}'
        if macd_col in df.columns:
            ax4.plot(df.index, df[macd_col], color='#00BFFF', linewidth=1.2, label='MACD')
            ax4.plot(df.index, df[macd_sig], color='#FF6347', linewidth=1.2, label='Signal')
        if macd_hist in df.columns:
            hc = ['#26a69a' if v >= 0 else '#ef5350' for v in df[macd_hist]]
            ax4.bar(df.index, df[macd_hist], color=hc, alpha=0.6, width=0.8)
        ax4.set_ylabel('MACD', color='white')
        ax4.axhline(0, color='#666', linewidth=0.5)

        plt.tight_layout()
        fig.savefig(save_path, dpi=150, facecolor='#1e1e1e', bbox_inches='tight')
        plt.close(fig)
        return save_path
