"""
data/backtest_trades.csv를 읽어 매매를 순서대로 복리 누적한 자산 곡선을 그리고,
최대낙폭(MDD) 구간(고점~저점)을 강조해 시각화하는 스크립트
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 한글이 깨지지 않도록 Windows 기본 한글 폰트(맑은 고딕) 지정
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

INPUT_PATH = "data/backtest_trades.csv"
OUTPUT_PATH = "data/backtest_equity_curve.png"

# 차트 색상 (fibo_indicator.py의 골든/데드크로스 색을 그대로 승/패 상태색으로 재사용)
COLOR_EQUITY = "#2a78d6"
COLOR_WIN = "#0ca30c"
COLOR_LOSS = "#d03b3b"
COLOR_SURFACE = "#fcfcfb"
COLOR_PRIMARY_INK = "#0b0b0b"
COLOR_MUTED = "#898781"
COLOR_GRID = "#e1e0d9"
COLOR_AXIS = "#c3c2b7"


def load_trades(path: str = INPUT_PATH) -> pd.DataFrame:
    """매매 내역 CSV를 읽고 매도일 기준으로 시간순 정렬한다."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["매도일"] = pd.to_datetime(df["매도일"])
    df = df.sort_values("매도일").reset_index(drop=True)
    return df


def compute_equity_curve(trades: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """매매 수익률을 순서대로 복리 누적한 자산 지수(시작=1.0)와, 그 시점까지의 고점 대비 낙폭을 계산한다."""
    cumulative = (1 + trades["수익률(%)"] / 100).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    return cumulative, drawdown


def plot_equity_curve(trades: pd.DataFrame, cumulative: pd.Series, drawdown: pd.Series, output_path: str):
    """자산 곡선 위에 매매별 승/패를 점으로 표시하고, 최대낙폭 구간(고점~저점)을 배경 강조 + 마커/주석으로 표시한다."""
    trough_idx = drawdown.idxmin()
    peak_idx = cumulative[:trough_idx + 1].idxmax()
    peak_date = trades.loc[peak_idx, "매도일"]
    trough_date = trades.loc[trough_idx, "매도일"]

    fig, ax = plt.subplots(figsize=(11, 6), dpi=150)
    fig.patch.set_facecolor(COLOR_SURFACE)
    ax.set_facecolor(COLOR_SURFACE)

    # 최대낙폭 구간을 배경으로 은은하게 강조
    ax.axvspan(peak_date, trough_date, color=COLOR_LOSS, alpha=0.08, zorder=0)
    ax.axhline(1.0, color=COLOR_AXIS, linewidth=1, linestyle="--", zorder=1)

    # 자산 곡선 (매매 순서대로 복리 누적)
    ax.plot(trades["매도일"], cumulative, color=COLOR_EQUITY, linewidth=2, zorder=2, label="누적자산(배)")

    # 매매별 승/패를 곡선 위 점으로 표시
    wins = trades["수익률(%)"] > 0
    ax.scatter(
        trades.loc[wins, "매도일"], cumulative[wins],
        s=30, facecolor=COLOR_WIN, edgecolor=COLOR_SURFACE, linewidth=0.8,
        zorder=3, label="수익 매매",
    )
    ax.scatter(
        trades.loc[~wins, "매도일"], cumulative[~wins],
        s=30, facecolor=COLOR_LOSS, edgecolor=COLOR_SURFACE, linewidth=0.8,
        zorder=3, label="손실 매매",
    )

    # 고점/저점 강조 마커 + 값 주석
    ax.scatter(
        [peak_date, trough_date], [cumulative[peak_idx], cumulative[trough_idx]],
        s=110, facecolor=COLOR_PRIMARY_INK, edgecolor=COLOR_SURFACE, linewidth=1.2,
        zorder=4, marker="o",
    )
    ax.annotate(
        f"고점 {cumulative[peak_idx]:.2f}배\n{peak_date.date()}",
        xy=(peak_date, cumulative[peak_idx]), xytext=(0, 14), textcoords="offset points",
        ha="center", fontsize=9, color=COLOR_PRIMARY_INK,
    )
    ax.annotate(
        f"저점 {cumulative[trough_idx]:.2f}배 ({drawdown[trough_idx] * 100:.1f}%)\n{trough_date.date()}",
        xy=(trough_date, cumulative[trough_idx]), xytext=(0, -34), textcoords="offset points",
        ha="center", fontsize=9, color=COLOR_PRIMARY_INK,
    )

    ax.set_title("백테스트 누적자산 곡선 및 최대낙폭(MDD) 구간", color=COLOR_PRIMARY_INK, fontsize=13, pad=12)
    ax.set_ylabel("누적자산 (시작=1.0배)", color=COLOR_MUTED, fontsize=10)

    ax.grid(True, axis="y", color=COLOR_GRID, linewidth=0.8)
    ax.grid(False, axis="x")
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["left", "bottom"]:
        ax.spines[spine].set_color(COLOR_AXIS)

    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.tick_params(axis="x", colors=COLOR_MUTED, labelsize=9, rotation=45)
    ax.tick_params(axis="y", colors=COLOR_MUTED, labelsize=9)

    ax.legend(loc="upper left", fontsize=9, frameon=False, labelcolor=COLOR_PRIMARY_INK)

    fig.tight_layout()
    fig.savefig(output_path, facecolor=COLOR_SURFACE)
    plt.close(fig)


def main():
    trades = load_trades()
    cumulative, drawdown = compute_equity_curve(trades)

    trough_idx = drawdown.idxmin()
    peak_idx = cumulative[:trough_idx + 1].idxmax()
    print(f"[INFO] 매매 건수: {len(trades)}건")
    print(f"[INFO] 고점: {trades.loc[peak_idx, '매도일'].date()} ({cumulative[peak_idx]:.3f}배)")
    print(f"[INFO] 저점: {trades.loc[trough_idx, '매도일'].date()} ({cumulative[trough_idx]:.3f}배, {drawdown[trough_idx] * 100:.2f}%)")

    plot_equity_curve(trades, cumulative, drawdown, OUTPUT_PATH)
    print(f"[INFO] 그래프 저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
