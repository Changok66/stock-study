"""
data/samsung.csv를 읽어 커스텀 일목균형표 지표인 엔상(N상)/엔하(N하), 그리고
현재 위치 기준 선행스팬인 선1/선2(양운/음운 판정용)를 계산하고,
종가 위에 시각화하는 스크립트.

엔상(N상):
- 1선: MA(종가, PERIOD)                                     → 단순 선
- 2선: MA(종가, PERIOD) + AVG(ATR(ATR_PERIOD), 10) × FACTOR       → 단순 선
- 3선: MA(종가, PERIOD) + AVG(ATR(ATR_PERIOD), 20) × FACTOR × 2   → 단순 선
- 4,5선: MA(종가, PERIOD) + AVG(ATR(ATR_PERIOD), 20) × FACTOR × 3/4 → 그 사이를 채운 구름대

엔하(N하):
- 1선: 후행스팬 = 종가를 LAG일만큼 앞당겨 표시한 값 (Close.shift(-LAG))       → 단순 선
- 2,3,4,5선: 엔상과 같은 방식이되 ATR 폭을 더해주는 대신 빼준다 (아래로 벌어짐)

ATR은 True Range의 단순 rolling mean(SMA)으로 계산한다
(backtest.py의 compute_adx()가 쓰는 Wilder 지수평활과는 다른 방식).

선1/선2 (일목 선행스팬, 현재 위치 - 미래로 미리 그리는 시프트 없음):
- 선1: (HH(SPAN1_SHORT) + LL(SPAN1_SHORT) + HH(SPAN1_LONG) + LL(SPAN1_LONG)) / 4
       = 두 기간(10일/25일)의 (최고가+최저가)/2 중간값을 다시 평균한 값
- 선2: (HH(SPAN2_PERIOD) + LL(SPAN2_PERIOD)) / 2  (50일 최고가/최저가의 중간값)
- 양운/음운: 선1 > 선2 이면 양운, 선1 < 선2 이면 음운 (backtest_multi.py의 매수 필터로 쓰인다)

FACTOR=1(2026-08-19 기준): 엔상/엔하는 백테스트 전략에 쓰이지 않는 참고용 지표라
영웅문 값과의 오차 보정(과거 FACTOR=1.1)은 걷어내고, 요청받은 원본 공식 그대로
FACTOR=1을 쓴다.
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 한글이 깨지지 않도록 Windows 기본 한글 폰트(맑은 고딕) 지정
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

INPUT_PATH = "data/samsung.csv"
OUTPUT_PATH = "data/samsung_ichimoku_custom.png"

# --- 지표 파라미터 (요청 값 그대로) ---
PERIOD = 17       # 기준 이동평균(MA) 기간, 엔상/엔하 공통
ATR_PERIOD = 14   # ATR 계산 기간
FACTOR = 1        # ATR 폭 계수
LAG = 25          # 엔하 1선(후행스팬)에 사용하는 이동 일수

# 2선은 AVG(ATR,10)×FACTOR×1, 3~5선은 AVG(ATR,20)×FACTOR×(2,3,4)
# (line_no, ATR을 평균 낼 기간 N, 배수)
LINE_SPECS = [
    (2, 10, 1),
    (3, 20, 2),
    (4, 20, 3),
    (5, 20, 4),
]

# --- 선1/선2(일목 선행스팬, 현재 위치) 파라미터 ---
SPAN1_SHORT = 10   # 선1에 쓰는 짧은 쪽 기간 (HH10/LL10)
SPAN1_LONG = 25    # 선1에 쓰는 긴 쪽 기간 (HH25/LL25)
SPAN2_PERIOD = 50  # 선2 기간 (HH50/LL50)

# 차트 색상 (팔레트 카테고리컬 슬롯: 1=blue, 2=orange, 3=aqua, 7=violet)
COLOR_CLOSE = "#2a78d6"      # 종가 (slot 1)
COLOR_EN_SANG = "#eb6834"    # 엔상 계열 (slot 2, fibo_indicator.py의 피보 구름과 동일 관례)
COLOR_EN_HA = "#4a3aa7"      # 엔하 계열 (slot 7, fibo_indicator.py의 역피보 구름과 동일 관례)
COLOR_SURFACE = "#fcfcfb"
COLOR_PRIMARY_INK = "#0b0b0b"
COLOR_MUTED = "#898781"
COLOR_GRID = "#e1e0d9"
COLOR_AXIS = "#c3c2b7"


def load_data(path: str) -> pd.DataFrame:
    """CSV를 읽고 Date 컬럼을 datetime으로 변환한 뒤 시간순으로 정렬한다."""
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    return df


def add_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.DataFrame:
    """
    ATR(Average True Range)을 계산한다.
    True Range의 단순 rolling mean(SMA)을 사용한다.
    """
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(window=period).mean()
    return df


def _envelope_line(ma: pd.Series, atr: pd.Series, avg_window: int, multiplier: int, sign: int) -> pd.Series:
    """MA(종가, PERIOD) ± AVG(ATR(ATR_PERIOD), avg_window) × FACTOR × multiplier"""
    band = atr.rolling(window=avg_window).mean() * FACTOR * multiplier
    return ma + sign * band


def add_en_sang(df: pd.DataFrame) -> pd.DataFrame:
    """엔상(N상): 17이평선을 중심으로 ATR 폭만큼 위로 벌어지는 1~5선."""
    ma = df["Close"].rolling(window=PERIOD).mean()
    df["엔상1선"] = ma
    for line_no, avg_window, multiplier in LINE_SPECS:
        df[f"엔상{line_no}선"] = _envelope_line(ma, df["ATR"], avg_window, multiplier, sign=1)
    return df


def add_en_ha(df: pd.DataFrame) -> pd.DataFrame:
    """엔하(N하): 1선은 후행스팬(종가를 LAG일 앞당겨 표시), 2~5선은 엔상과 같되 ATR 폭만큼 아래로 벌어진다."""
    ma = df["Close"].rolling(window=PERIOD).mean()
    df["엔하1선"] = df["Close"].shift(-LAG)
    for line_no, avg_window, multiplier in LINE_SPECS:
        df[f"엔하{line_no}선"] = _envelope_line(ma, df["ATR"], avg_window, multiplier, sign=-1)
    return df


def add_senkou_spans(df: pd.DataFrame) -> pd.DataFrame:
    """
    선1/선2(일목 선행스팬, 현재 위치 - 미래로 미리 그리는 시프트 없음)와
    그 대소 관계로 정하는 양운/음운 상태를 계산한다.

    선1 = (HH(SPAN1_SHORT) + LL(SPAN1_SHORT) + HH(SPAN1_LONG) + LL(SPAN1_LONG)) / 4
    선2 = (HH(SPAN2_PERIOD) + LL(SPAN2_PERIOD)) / 2
    (HHn/LLn = 최근 n일 고가/저가의 최대값/최소값)
    """
    hh_short = df["High"].rolling(window=SPAN1_SHORT).max()
    ll_short = df["Low"].rolling(window=SPAN1_SHORT).min()
    hh_long = df["High"].rolling(window=SPAN1_LONG).max()
    ll_long = df["Low"].rolling(window=SPAN1_LONG).min()
    hh_span2 = df["High"].rolling(window=SPAN2_PERIOD).max()
    ll_span2 = df["Low"].rolling(window=SPAN2_PERIOD).min()

    df["선1"] = (hh_short + ll_short + hh_long + ll_long) / 4
    df["선2"] = (hh_span2 + ll_span2) / 2
    df["구름상태"] = df["선1"].gt(df["선2"]).map({True: "양운", False: "음운"})
    df.loc[df["선1"].isna() | df["선2"].isna(), "구름상태"] = None
    return df


def plot_ichimoku_custom(df: pd.DataFrame, output_path: str):
    """
    종가 위에 엔상(1~3선은 단순 선, 4·5선은 구름대)과
    엔하(1선은 후행스팬, 2·3선은 단순 선, 4·5선은 구름대)를 겹쳐 그린다.
    """
    fig, ax = plt.subplots(figsize=(11, 6), dpi=150)
    fig.patch.set_facecolor(COLOR_SURFACE)
    ax.set_facecolor(COLOR_SURFACE)

    # 구름대(4~5선)를 먼저 그려 배경처럼 깔리게 한다
    ax.fill_between(
        df["Date"], df["엔상4선"], df["엔상5선"],
        color=COLOR_EN_SANG, alpha=0.20, linewidth=0,
        label="엔상 구름 (4선~5선)", zorder=1,
    )
    ax.fill_between(
        df["Date"], df["엔하4선"], df["엔하5선"],
        color=COLOR_EN_HA, alpha=0.20, linewidth=0,
        label="엔하 구름 (4선~5선)", zorder=1,
    )

    # 엔상 1~3선
    ax.plot(df["Date"], df["엔상1선"], color=COLOR_EN_SANG, linewidth=1.8, label="엔상1선 (17이평)", zorder=2)
    ax.plot(df["Date"], df["엔상2선"], color=COLOR_EN_SANG, linewidth=1.0, linestyle="--", alpha=0.85, label="엔상2선", zorder=2)
    ax.plot(df["Date"], df["엔상3선"], color=COLOR_EN_SANG, linewidth=1.0, linestyle=":", alpha=0.85, label="엔상3선", zorder=2)

    # 엔하 2~3선 (1선인 후행스팬은 차트에서 제외)
    ax.plot(df["Date"], df["엔하2선"], color=COLOR_EN_HA, linewidth=1.0, linestyle="--", alpha=0.85, label="엔하2선", zorder=2)
    ax.plot(df["Date"], df["엔하3선"], color=COLOR_EN_HA, linewidth=1.0, linestyle=":", alpha=0.85, label="엔하3선", zorder=2)

    # 종가는 맨 위(zorder 최상단)에 그려서 항상 잘 보이도록 한다
    ax.plot(df["Date"], df["Close"], color=COLOR_CLOSE, linewidth=2, label="종가", zorder=3)

    ax.set_title("삼성전자(005930) 종가 + 엔상/엔하 (커스텀 일목균형표)", color=COLOR_PRIMARY_INK, fontsize=13, pad=12)
    ax.set_xlabel("")
    ax.set_ylabel("가격 (원)", color=COLOR_MUTED, fontsize=10)

    ax.grid(True, axis="y", color=COLOR_GRID, linewidth=0.8)
    ax.grid(False, axis="x")
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["left", "bottom"]:
        ax.spines[spine].set_color(COLOR_AXIS)

    # 5년치 데이터라 매달 표시하면 라벨이 겹치므로 6개월 간격으로 표시
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.tick_params(axis="x", colors=COLOR_MUTED, labelsize=9, rotation=45)
    ax.tick_params(axis="y", colors=COLOR_MUTED, labelsize=9)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v):,}"))

    ax.legend(loc="upper left", fontsize=8, frameon=False, labelcolor=COLOR_PRIMARY_INK, ncol=2)

    fig.tight_layout()
    fig.savefig(output_path, facecolor=COLOR_SURFACE)
    plt.close(fig)


def main():
    df = load_data(INPUT_PATH)

    df = add_atr(df)
    df = add_en_sang(df)
    df = add_en_ha(df)
    df = add_senkou_spans(df)

    print(f"[INFO] 데이터 기간: {df['Date'].min().date()} ~ {df['Date'].max().date()}")
    print(f"[INFO] 계산된 컬럼: {list(df.columns)}")

    plot_ichimoku_custom(df, OUTPUT_PATH)
    print(f"[INFO] 그래프 저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
