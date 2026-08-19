"""
data/samsung.csv를 읽어 지수이동평균(EMA), 피보나치 지표, 볼린저밴드,
역피보나치 지표를 계산하고, 종가 위에 두 개의 구름(band) 형태로 시각화하는 스크립트
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 한글이 깨지지 않도록 Windows 기본 한글 폰트(맑은 고딕) 지정
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

INPUT_PATH = "data/samsung.csv"
OUTPUT_PATH = "data/samsung_fibo_cloud.png"

# 차트 색상
COLOR_CLOSE = "#2a78d6"       # 종가 선 (팔레트 1번 slot: blue)
COLOR_FIBO_CLOUD = "#eb6834"  # 피보 구름 (팔레트 2번 slot: orange)
COLOR_INV_FIBO_CLOUD = "#4a3aa7"  # 역피보 구름 (팔레트 7번 slot: violet)
COLOR_SURFACE = "#fcfcfb"
COLOR_PRIMARY_INK = "#0b0b0b"
COLOR_MUTED = "#898781"
COLOR_GRID = "#e1e0d9"
COLOR_AXIS = "#c3c2b7"
COLOR_GOLDEN_CROSS = "#0ca30c"  # 골든크로스 표식 (상태색: good)
COLOR_DEAD_CROSS = "#d03b3b"    # 데드크로스 표식 (상태색: critical)


def load_data(path: str) -> pd.DataFrame:
    """CSV를 읽고 Date 컬럼을 datetime으로 변환한 뒤 시간순으로 정렬한다."""
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    return df


def add_ma(df: pd.DataFrame) -> pd.DataFrame:
    """
    종가(Close) 기준 단순이동평균(SMA)을 계산한다.
    MA5/MA8/MA13은 각각 5일/8일/13일 구간 종가의 산술평균이다.
    """
    df["MA5"] = df["Close"].rolling(window=5).mean()
    df["MA8"] = df["Close"].rolling(window=8).mean()
    df["MA13"] = df["Close"].rolling(window=13).mean()
    return df


def add_fibo(df: pd.DataFrame) -> pd.DataFrame:
    """
    피보나치 지표(단기~중기 EMA의 중간값)를 계산한다.
    - 피보4: 5일 EMA와 8일 EMA의 평균 (더 단기)
    - 피보5: 8일 EMA와 13일 EMA의 평균 (더 장기)
    이 두 값 사이의 영역을 '피보 구름'으로 표시한다.
    """
    df["피보4"] = (df["MA5"] + df["MA8"]) / 2
    df["피보5"] = (df["MA8"] + df["MA13"]) / 2
    return df


def add_bollinger_bands(df: pd.DataFrame) -> pd.DataFrame:
    """
    볼린저밴드를 두 가지 폭으로 계산한다.
    - 좁은 밴드: 13일 기간, 표준편차 1배 (단기 변동 범위)
    - 넓은 밴드: 21일 기간, 표준편차 2배 (일반적인 볼린저밴드 표준 설정)
    중심선은 각 기간의 단순이동평균(SMA), 밴드 폭은 해당 기간 종가의 표준편차를 사용한다.
    ddof=0(모집단 표준편차)을 사용해 일반적인 볼린저밴드 공식을 따른다.
    """
    # --- 좁은 밴드 (13일, ±1 표준편차) ---
    narrow_window = 13
    narrow_ma = df["Close"].rolling(window=narrow_window).mean()
    narrow_std = df["Close"].rolling(window=narrow_window).std(ddof=0)
    df["BB상단_좁음"] = narrow_ma + 1 * narrow_std
    df["BB하단_좁음"] = narrow_ma - 1 * narrow_std

    # --- 넓은 밴드 (21일, ±2 표준편차) ---
    wide_window = 21
    wide_ma = df["Close"].rolling(window=wide_window).mean()
    wide_std = df["Close"].rolling(window=wide_window).std(ddof=0)
    df["BB상단_넓음"] = wide_ma + 2 * wide_std
    df["BB하단_넓음"] = wide_ma - 2 * wide_std

    return df


def add_inverse_fibo(df: pd.DataFrame) -> pd.DataFrame:
    """
    역피보나치 지표를 계산한다.
    볼린저밴드 4개 값(상단_좁음/넓음, 하단_좁음/넓음)의 평균을 기준점으로 잡고,
    그 기준점을 중심으로 피보4/피보5를 반대편으로 대칭 이동(2 * 기준 - 피보값)시킨 값이다.
    - 역피보4: 볼린저밴드 평균 기준, 피보4(단기)의 대칭점
    - 역피보5: 볼린저밴드 평균 기준, 피보5(장기)의 대칭점
    """
    bb_mean = (
        df["BB상단_좁음"] + df["BB상단_넓음"] + df["BB하단_좁음"] + df["BB하단_넓음"]
    ) / 4

    df["역피보4"] = 2 * bb_mean - df["피보4"]
    df["역피보5"] = 2 * bb_mean - df["피보5"]
    return df


def detect_cloud_crossovers(df: pd.DataFrame) -> pd.DataFrame:
    """
    피보 구름과 역피보 구름이 서로 교차하는 지점(골든크로스/데드크로스)을 찾는다.
    각 구름을 대표하는 중심값(상단·하단 평균)을 비교해, 그 대소 관계가 뒤집히는 날을 교차일로 본다.
    - 골든크로스: 피보 구름 중심이 역피보 구름 중심 아래에서 위로 올라선 시점
    - 데드크로스: 그 반대로, 위에서 아래로 내려간 시점
    볼린저 21일 밴드가 필요해 초반 20거래일은 NaN이므로 계산 전 제외한다.
    """
    valid = df.dropna(subset=["피보4", "피보5", "역피보4", "역피보5"]).reset_index(drop=True)

    fibo_center = (valid["피보4"] + valid["피보5"]) / 2
    inv_fibo_center = (valid["역피보4"] + valid["역피보5"]) / 2
    diff = fibo_center - inv_fibo_center
    sign = diff.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

    rows = []
    prev_sign = None
    for i in range(len(valid)):
        s = sign.iloc[i]
        if prev_sign is not None and s != prev_sign and s != 0 and prev_sign != 0:
            rows.append({
                "Date": valid["Date"].iloc[i],
                "종류": "골든크로스" if s == 1 else "데드크로스",
                "Close": valid["Close"].iloc[i],
            })
        prev_sign = s

    return pd.DataFrame(rows)


def plot_fibo_cloud(df: pd.DataFrame, crossovers: pd.DataFrame, output_path: str):
    """
    종가 선 그래프 위에 두 개의 구름(반투명 채움 영역)을 겹쳐 그리고,
    두 구름의 골든크로스/데드크로스 지점을 종가 선 위에 마커로 표시한다.
    - 피보 구름: 피보4 ~ 피보5 사이 영역 (주황 계열, 반투명)
    - 역피보 구름: 역피보4 ~ 역피보5 사이 영역 (보라 계열, 반투명)
    - 골든크로스: 초록 위쪽 삼각형 / 데드크로스: 빨강 아래쪽 삼각형
    fill_between은 두 선의 대소 관계가 바뀌어도(교차해도) 항상 그 사이를 채워준다.
    """
    fig, ax = plt.subplots(figsize=(11, 6), dpi=150)
    fig.patch.set_facecolor(COLOR_SURFACE)
    ax.set_facecolor(COLOR_SURFACE)

    # 구름(밴드)을 먼저 그려 종가 선 아래 배경처럼 깔리게 한다 (zorder로 순서 제어)
    ax.fill_between(
        df["Date"], df["피보4"], df["피보5"],
        color=COLOR_FIBO_CLOUD, alpha=0.25, linewidth=0,
        label="피보 구름 (피보4~피보5)", zorder=1,
    )
    ax.fill_between(
        df["Date"], df["역피보4"], df["역피보5"],
        color=COLOR_INV_FIBO_CLOUD, alpha=0.25, linewidth=0,
        label="역피보 구름 (역피보4~역피보5)", zorder=1,
    )

    # 종가 선은 구름 위(zorder 높음)에 그려서 항상 잘 보이도록 한다
    ax.plot(df["Date"], df["Close"], color=COLOR_CLOSE, linewidth=2, label="종가", zorder=3)

    # 골든크로스/데드크로스 지점을 종가 선 위에 마커로 표시 (마커 위(zorder 최상단))
    golden = crossovers[crossovers["종류"] == "골든크로스"]
    dead = crossovers[crossovers["종류"] == "데드크로스"]
    ax.scatter(
        golden["Date"], golden["Close"],
        marker="^", s=90, facecolor=COLOR_GOLDEN_CROSS, edgecolor=COLOR_SURFACE, linewidth=1,
        label="골든크로스", zorder=4,
    )
    ax.scatter(
        dead["Date"], dead["Close"],
        marker="v", s=90, facecolor=COLOR_DEAD_CROSS, edgecolor=COLOR_SURFACE, linewidth=1,
        label="데드크로스", zorder=4,
    )

    ax.set_title("삼성전자(005930) 종가 + 피보/역피보 구름", color=COLOR_PRIMARY_INK, fontsize=13, pad=12)
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

    # 계열(종가 + 구름 2개)이 여러 개이므로 범례를 항상 표시
    ax.legend(loc="upper left", fontsize=9, frameon=False, labelcolor=COLOR_PRIMARY_INK)

    fig.tight_layout()
    fig.savefig(output_path, facecolor=COLOR_SURFACE)
    plt.close(fig)


def main():
    df = load_data(INPUT_PATH)

    # 1. 이동평균(SMA)
    df = add_ma(df)

    # 2. 피보나치 지표
    df = add_fibo(df)

    # 3. 볼린저밴드 (좁은 밴드 + 넓은 밴드)
    df = add_bollinger_bands(df)

    # 4. 역피보나치 지표
    df = add_inverse_fibo(df)

    # 5. 골든크로스/데드크로스 지점 탐지
    crossovers = detect_cloud_crossovers(df)

    print(f"[INFO] 데이터 기간: {df['Date'].min().date()} ~ {df['Date'].max().date()}")
    print(f"[INFO] 계산된 컬럼: {list(df.columns)}")
    print(f"[INFO] 구름 교차 지점: {len(crossovers)}건")

    # 6. 종가 + 피보/역피보 구름 + 교차 지점 시각화
    plot_fibo_cloud(df, crossovers, OUTPUT_PATH)
    print(f"[INFO] 그래프 저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
