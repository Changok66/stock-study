"""
data/samsung.csv를 읽어 Date 컬럼을 datetime으로 변환한 뒤
삼성전자 종가(Close)와 거래량(Volume) 추이를 시간순으로 그려 PNG로 저장하는 스크립트
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 한글이 깨지지 않도록 Windows 기본 한글 폰트(맑은 고딕) 지정
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

INPUT_PATH = "data/samsung.csv"
OUTPUT_PATH = "data/samsung_price_volume.png"

# 차트 색상 (팔레트 카테고리컬 슬롯: 1=blue, 2=orange, 3=aqua, 8=red)
COLOR_CLOSE = "#2a78d6"
COLOR_MA20 = "#eb6834"
COLOR_MA60 = "#1baf7a"
COLOR_HIGHLIGHT = "#e34948"
COLOR_SURFACE = "#fcfcfb"
COLOR_PRIMARY_INK = "#0b0b0b"
COLOR_MUTED = "#898781"
COLOR_GRID = "#e1e0d9"
COLOR_AXIS = "#c3c2b7"

TOP_N = 10  # 거래량 상위 며칠을 표시할지


def load_data(path: str) -> pd.DataFrame:
    """CSV를 읽고 Date 컬럼을 datetime으로 변환한 뒤 시간순으로 정렬한다."""
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    return df


def add_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    """종가 기준 20일선(단기)과 60일선(중기) 이동평균을 추가한다."""
    df["MA20"] = df["Close"].rolling(window=20).mean()
    df["MA60"] = df["Close"].rolling(window=60).mean()
    return df


def get_top_volume_days(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """거래량 기준 상위 n개 거래일을 반환한다 (표에서 뽑았던 것과 동일한 기준)."""
    return df.sort_values("Volume", ascending=False).head(n)


def plot_price_and_volume(df: pd.DataFrame, top_volume: pd.DataFrame, output_path: str):
    """
    종가(Close) + 이동평균선(MA20/MA60)과 거래량(Volume)을 시간순으로 그리고,
    거래량 상위 n개 거래일을 두 서브플롯 모두에 강조 표시한다.
    가격(원)과 거래량(주)은 단위가 완전히 달라 한 축에 같이 그리면(이중 축) 왜곡되어 보이므로,
    x축(날짜)을 공유하는 두 개의 별도 서브플롯(위: 가격, 아래: 거래량)으로 분리한다.
    """
    fig, (ax_price, ax_volume) = plt.subplots(
        2, 1, figsize=(11, 6.5), dpi=150,
        sharex=True, gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
    )
    fig.patch.set_facecolor(COLOR_SURFACE)

    # --- 위: 종가 + 이동평균선 ---
    ax_price.set_facecolor(COLOR_SURFACE)
    ax_price.plot(df["Date"], df["Close"], color=COLOR_CLOSE, linewidth=2, label="종가", zorder=2)
    ax_price.plot(df["Date"], df["MA20"], color=COLOR_MA20, linewidth=1.3, label="20일 이동평균", zorder=2)
    ax_price.plot(df["Date"], df["MA60"], color=COLOR_MA60, linewidth=1.3, label="60일 이동평균", zorder=2)
    # 거래량 상위 n일을 종가 라인 위에 마커로 강조
    ax_price.scatter(
        top_volume["Date"], top_volume["Close"],
        s=45, facecolor=COLOR_HIGHLIGHT, edgecolor=COLOR_SURFACE, linewidth=1,
        zorder=3, label=f"거래량 상위 {TOP_N}일",
    )
    ax_price.set_title("삼성전자(005930) 종가·이동평균선 및 거래량 추이 (최근 5년)", color=COLOR_PRIMARY_INK, fontsize=13, pad=12)
    ax_price.set_ylabel("종가 (원)", color=COLOR_MUTED, fontsize=10)
    ax_price.grid(True, axis="y", color=COLOR_GRID, linewidth=0.8)
    ax_price.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax_price.tick_params(axis="y", colors=COLOR_MUTED, labelsize=9)
    # 계열이 4개(종가/MA20/MA60/강조마커)이므로 범례를 항상 표시
    legend = ax_price.legend(loc="upper left", fontsize=9, frameon=False, labelcolor=COLOR_PRIMARY_INK)

    # --- 아래: 거래량 막대 그래프 (상위 n일은 강조 색으로 구분) ---
    ax_volume.set_facecolor(COLOR_SURFACE)
    top_dates = set(top_volume["Date"])
    bar_colors = [COLOR_HIGHLIGHT if d in top_dates else COLOR_CLOSE for d in df["Date"]]
    bar_alphas = [0.85 if d in top_dates else 0.55 for d in df["Date"]]
    ax_volume.bar(df["Date"], df["Volume"], width=1.0, color=bar_colors, alpha=None)
    for bar, a in zip(ax_volume.patches, bar_alphas):
        bar.set_alpha(a)
    ax_volume.set_ylabel("거래량 (백만 주)", color=COLOR_MUTED, fontsize=10)
    ax_volume.grid(True, axis="y", color=COLOR_GRID, linewidth=0.8)
    # 거래량은 값이 커서(천만 단위) 백만 주 단위로 환산해 표시
    ax_volume.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v / 1e6:,.0f}"))
    ax_volume.tick_params(axis="y", colors=COLOR_MUTED, labelsize=9)

    # 날짜 축 눈금은 맨 아래 서브플롯에만 표시 (x축 공유)
    # 5년치 데이터라 매달 표시하면 라벨이 겹치므로 6개월 간격으로 표시
    ax_volume.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax_volume.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax_volume.tick_params(axis="x", colors=COLOR_MUTED, labelsize=9, rotation=45)

    # 공통 스타일: 위쪽/오른쪽 테두리 제거, 남은 축선은 절제된 색으로
    for ax in (ax_price, ax_volume):
        ax.grid(False, axis="x")
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        for spine in ["left", "bottom"]:
            ax.spines[spine].set_color(COLOR_AXIS)

    fig.tight_layout()
    fig.savefig(output_path, facecolor=COLOR_SURFACE)
    plt.close(fig)


def main():
    df = load_data(INPUT_PATH)
    df = add_moving_averages(df)
    top_volume = get_top_volume_days(df, TOP_N)

    print(f"[INFO] Date dtype: {df['Date'].dtype}")
    print(f"[INFO] 데이터 기간: {df['Date'].min().date()} ~ {df['Date'].max().date()}")
    print(f"[INFO] 거래량 상위 {TOP_N}일: {', '.join(top_volume['Date'].dt.strftime('%Y-%m-%d'))}")

    plot_price_and_volume(df, top_volume, OUTPUT_PATH)
    print(f"[INFO] 그래프 저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
