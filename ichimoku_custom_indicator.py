"""
data/samsung.csv를 읽어 커스텀 일목균형표 지표인 엔상(N상)/엔하(N하)를 계산하고,
종가 위에 시각화하는 스크립트.

엔상(N상):
- 1선: MA(종가, PERIOD)                                           → 단순 선
- 2선: shift(MA(종가, PERIOD) + AVG(ATR(ATR_PERIOD), 10) × FACTOR,       AA) → 단순 선
- 3선: shift(MA(종가, PERIOD) + AVG(ATR(ATR_PERIOD), 20) × FACTOR × 2,   AA) → 단순 선
- 4,5선: shift(MA(종가, PERIOD) + AVG(ATR(ATR_PERIOD), 20) × FACTOR × 3/4, AA) → 그 사이를 채운 구름대

엔하(N하):
- 1선: 후행스팬 = 종가를 LAG일만큼 앞당겨 표시한 값 (Close.shift(-LAG))       → 단순 선
- 2,3,4,5선: 엔상과 같은 방식이되 ATR 폭을 더해주는 대신 빼준다 (아래로 벌어짐)

ATR은 True Range의 단순 rolling mean(SMA)으로 계산한다
(backtest.py의 compute_adx()가 쓰는 Wilder 지수평활과는 다른 방식).

--- 2026-08-14 영웅문 검증 기록 ---
- 이 지표는 영웅문 표준 내장 지표가 아니라, 사용자가 EnvelopeUp을 ATR 기반으로
  직접 변형한 커스텀 지표다.
- 공식 구조(MA ± AVG(ATR,N)×FACTOR×배수)는 검증됨: 2026-07-14 기준 영웅문 실측치와
  비교했을 때 1선(17이평)~피보/역피보는 오차 1% 이내, 배수가 큰 4·5선까지 포함해도
  오차 1~7% 범위였다.
- 영웅문 쪽 "Percent" 파라미터는 이 지표에서 사용되지 않는다(원/절대값 기준 밴드).
- 남은 오차(주로 4·5선)는 영웅문 내부의 AVG/ATR 계산 디테일(예: rolling 평균을
  몇 단계 거치는지 등) 차이로 추정되며 확정하지 못했다. 아래 계산값은 참고용
  근사치이며, 영웅문 실제 표시값과는 소폭 차이가 있을 수 있다.
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
AA = 0            # 2~5선 전체에 적용하는 시프트 (현재 0 = 시프트 없음)
LAG = 25          # 엔하 1선(후행스팬)에 사용하는 이동 일수

# 2선은 AVG(ATR,10)×FACTOR×1, 3~5선은 AVG(ATR,20)×FACTOR×(2,3,4)
# (line_no, ATR을 평균 낼 기간 N, 배수)
LINE_SPECS = [
    (2, 10, 1),
    (3, 20, 2),
    (4, 20, 3),
    (5, 20, 4),
]

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
    """shift(MA(종가, PERIOD) ± AVG(ATR(ATR_PERIOD), avg_window) × FACTOR × multiplier, AA)"""
    band = atr.rolling(window=avg_window).mean() * FACTOR * multiplier
    return (ma + sign * band).shift(AA)


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

    print(f"[INFO] 데이터 기간: {df['Date'].min().date()} ~ {df['Date'].max().date()}")
    print(f"[INFO] 계산된 컬럼: {list(df.columns)}")

    plot_ichimoku_custom(df, OUTPUT_PATH)
    print(f"[INFO] 그래프 저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
