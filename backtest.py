"""
fibo_indicator.py의 골든크로스/데드크로스 로직을 재사용해
"골든크로스 발생 + ADX > 25(추세 있음)일 때만 다음날 시가 매수 ->
데드크로스 발생 시 다음날 시가 매도" 전략을 백테스트하는 스크립트.
매매 수수료/거래세를 반영한 매매별 수익률, 전체 누적 수익률과
비교 기준인 매수 후 보유(Buy & Hold) 수익률을 함께 계산한다.
"""

import argparse

import pandas as pd

import fibo_indicator as fi

# --- 학습/검증 구간 분리 ---
# 학습 구간(train)에서만 ADX_THRESHOLD 등 전략 조건을 조정하고,
# 검증 구간(val)은 조정된 조건을 한 번도 보여주지 않은 채 마지막에 딱 한 번만 시험한다.
# 지표(EMA/볼린저밴드/ADX)는 항상 전체 데이터로 계산한 뒤, 매매 신호만 구간으로 잘라서 본다 -
# 그래야 검증 구간 초반(2025년 1월경) 지표도 워밍업 부족 없이 정확하게 계산된다.
SPLIT_RANGES: dict[str, tuple[pd.Timestamp | None, pd.Timestamp | None]] = {
    "train": (pd.Timestamp("2021-01-01"), pd.Timestamp("2024-12-31")),
    "val": (pd.Timestamp("2025-01-01"), pd.Timestamp("2026-12-31")),
    "all": (None, None),
}

# --- 수수료 관련 상수 ---
BUY_FEE_RATE = 0.00015                    # 매수 수수료 0.015%
SELL_FEE_RATE = 0.00015 + 0.0018          # 매도 수수료 0.015% + 거래세 0.18%

# --- ADX(추세 강도 지표) 관련 상수 ---
ADX_PERIOD = 14        # ADX 계산에 쓰는 기간 (관례적으로 14일)
ADX_THRESHOLD = 25      # 이 값을 넘으면 "추세가 있다"고 판단하는 기준선 (관례적으로 25)

# 데드크로스 외에, 보유 중 ADX가 임계값 아래로 떨어질 때도 청산할지 여부.
# 요청에서 "청산도 고려 가능"으로 언급된 선택 사항이라 기본은 끔(False) -
# 기본 매도 신호는 데드크로스만 사용하고, 켜면 추세 소멸 시 데드크로스 전에도 먼저 빠져나온다.
EXIT_ON_ADX_WEAKEN = False

TRADES_OUTPUT_PATH = "data/backtest_trades.csv"


def compute_adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.Series:
    """
    ADX(Average Directional Index, 평균방향지수)를 계산한다.
    가격이 "얼마나 잘 추세를 타고 있는지"(방향과 무관하게 추세의 강도)를 0~100 사이 값으로 나타낸다.
    통상 25를 넘으면 뚜렷한 추세, 20 아래면 방향성 없는 횡보 구간으로 해석한다.

    계산 순서:
    1. True Range(TR): 당일 변동폭을 (고가-저가), (고가-전일종가), (저가-전일종가) 중 최대값으로 산정
    2. +DM/-DM: 상승 방향/하락 방향으로의 순수 움직임 크기
    3. TR, +DM, -DM을 각각 Wilder 방식으로 지수평활 (alpha=1/period인 EWM과 수학적으로 동일)
    4. +DI, -DI: 평활된 +DM/-DM을 평활된 TR로 나눠 백분율로 표현한 방향 지표
    5. DX: +DI와 -DI의 차이를 둘의 합으로 나눈 값 (방향성의 뚜렷한 정도)
    6. ADX: DX를 다시 Wilder 방식으로 지수평활한 값 (최종 추세 강도)
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    # 1. True Range
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    # 2. 상승/하락 방향성 움직임 (둘 중 더 크고, 0보다 큰 쪽만 인정)
    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)
    plus_mask = (up_move > down_move) & (up_move > 0)
    minus_mask = (down_move > up_move) & (down_move > 0)
    plus_dm[plus_mask] = up_move[plus_mask]
    minus_dm[minus_mask] = down_move[minus_mask]

    # 3~4. Wilder 지수평활(alpha=1/period, adjust=False) 후 +DI/-DI 산출
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr

    # 5~6. DX -> ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()

    return adx


def prepare_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    fibo_indicator.py의 함수들을 재사용해 지표가 계산된 전체 데이터프레임을 만들고,
    골든크로스/데드크로스 지점과 ADX를 추가로 계산한다.
    """
    df = fi.load_data(fi.INPUT_PATH)
    df = fi.add_ema(df)
    df = fi.add_fibo(df)
    df = fi.add_bollinger_bands(df)
    df = fi.add_inverse_fibo(df)

    crossovers = fi.detect_cloud_crossovers(df)
    crossovers = crossovers.sort_values("Date").reset_index(drop=True)

    df["ADX"] = compute_adx(df)

    return df, crossovers


def filter_by_split(df: pd.DataFrame, crossovers: pd.DataFrame, split: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    지표가 이미 계산된 전체 df/crossovers를, 학습/검증 구간 경계로만 잘라낸다.
    지표 계산에는 영향을 주지 않고(전체 데이터로 이미 계산됨) 매매 신호 탐색 범위만 좁힌다.
    """
    start, end = SPLIT_RANGES[split]
    if start is not None:
        df = df[df["Date"] >= start]
        crossovers = crossovers[crossovers["Date"] >= start]
    if end is not None:
        df = df[df["Date"] <= end]
        crossovers = crossovers[crossovers["Date"] <= end]

    return df.reset_index(drop=True), crossovers.reset_index(drop=True)


def run_backtest(
    df: pd.DataFrame, crossovers: pd.DataFrame, use_adx_filter: bool = True,
) -> tuple[pd.DataFrame, dict | None, int]:
    """
    매수: 골든크로스가 뜨면 다음 거래일 시가로 매수.
          use_adx_filter=True(기본값)면 그날 ADX > ADX_THRESHOLD(추세 있음)일 때만 매수하고,
          False면 ADX와 무관하게 골든크로스마다 매수한다(원본 피보/역피보 지표 그대로).
    매도: 데드크로스가 뜨면 다음 거래일 시가로 매도
          (EXIT_ON_ADX_WEAKEN=True이면, 보유 중 ADX가 ADX_THRESHOLD 아래로 떨어져도 다음 거래일 시가로 매도)

    - 이미 보유 중일 때 골든크로스가 또 뜨면 무시(중복 매수 방지)
    - 보유 중이 아닐 때 매도 신호가 뜨면 무시(팔 물량이 없으므로)
    - 골든크로스가 떴지만 ADX 조건을 만족하지 못해 매수하지 않은 횟수도 진단용으로 함께 센다
    - 신호일이 데이터의 마지막 날이라 "다음 거래일"이 없으면 그 신호는 실행하지 못하고 건너뛴다
    - 데이터 끝까지 매도 신호가 나오지 않아 포지션이 남으면(미청산),
      매매 표에는 넣지 않고 별도로 반환한다.

    반환값: (완료된 매매 내역 DataFrame, 미청산 포지션 정보 dict 또는 None, ADX 필터로 건너뛴 골든크로스 수)
    """
    df = df.sort_values("Date").reset_index(drop=True)
    golden_dates = set(crossovers.loc[crossovers["종류"] == "골든크로스", "Date"])
    dead_dates = set(crossovers.loc[crossovers["종류"] == "데드크로스", "Date"])

    trades = []
    position = None  # {"buy_date":..., "buy_price":..., "buy_adx":...} 형태로 보유 중인 매수 정보 저장
    skipped_weak_adx = 0

    # 마지막 행은 "다음 거래일"이 없어 그날 신호가 떠도 실행할 수 없으므로 반복에서 제외
    for i in range(len(df) - 1):
        row = df.iloc[i]
        next_day = df.iloc[i + 1]
        date = row["Date"]
        adx = row["ADX"]

        if position is None:
            if date in golden_dates:
                passes_adx = (not use_adx_filter) or (pd.notna(adx) and adx > ADX_THRESHOLD)
                if passes_adx:
                    # (필터 미사용이거나) 추세 있음 확인 -> 다음 거래일 시가로 매수
                    position = {
                        "buy_date": next_day["Date"],
                        "buy_price": next_day["Open"],
                        "buy_adx": adx,
                    }
                else:
                    # 골든크로스는 떴지만 추세 강도가 부족해 매매 보류
                    skipped_weak_adx += 1

        else:
            is_dead_cross = date in dead_dates
            is_adx_weak = EXIT_ON_ADX_WEAKEN and pd.notna(adx) and adx < ADX_THRESHOLD

            if is_dead_cross or is_adx_weak:
                sell_date = next_day["Date"]
                sell_price = next_day["Open"]
                buy_date = position["buy_date"]
                buy_price = position["buy_price"]

                buy_cost = buy_price * (1 + BUY_FEE_RATE)         # 매수 시 실제 지불 금액(수수료 포함)
                sell_proceeds = sell_price * (1 - SELL_FEE_RATE)  # 매도 시 실제 수령 금액(수수료+거래세 차감)
                return_rate = sell_proceeds / buy_cost - 1

                trades.append({
                    "매수일": buy_date,
                    "매도일": sell_date,
                    "매수가": buy_price,
                    "매도가": sell_price,
                    "매수시ADX": round(position["buy_adx"], 1),
                    "매도사유": "데드크로스" if is_dead_cross else "ADX약화",
                    "수익률(%)": round(return_rate * 100, 2),
                })
                position = None

    trades_df = pd.DataFrame(trades)
    return trades_df, position, skipped_weak_adx


def compute_cumulative_return(trades_df: pd.DataFrame) -> float:
    """
    각 매매 수익률을 복리로 누적한 전체 누적 수익률(%)을 계산한다.
    예: +10% 매매 후 -5% 매매 -> (1.10 * 0.95) - 1
    """
    if trades_df.empty:
        return 0.0

    cumulative = 1.0
    for r in trades_df["수익률(%)"]:
        cumulative *= (1 + r / 100)

    return (cumulative - 1) * 100


def compute_buy_and_hold_return(df: pd.DataFrame) -> float:
    """
    "처음부터 끝까지 그냥 들고만 있었을 때"의 수익률을 계산한다.
    전략과 동일한 기준으로 비교하기 위해, 첫날 시가로 매수(매수 수수료 반영)해
    마지막날 종가로 매도(매도 수수료+거래세 반영)한다고 가정한다.
    """
    df = df.sort_values("Date").reset_index(drop=True)

    buy_price = df.iloc[0]["Open"]
    sell_price = df.iloc[-1]["Close"]

    buy_cost = buy_price * (1 + BUY_FEE_RATE)
    sell_proceeds = sell_price * (1 - SELL_FEE_RATE)

    return (sell_proceeds / buy_cost - 1) * 100


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="골든/데드크로스 + ADX 필터 백테스트")
    parser.add_argument(
        "--split", choices=list(SPLIT_RANGES.keys()), default="all",
        help="train=학습 구간(2021~2024)만, val=검증 구간(2025~2026)만, all=전체 구간(기본값)",
    )
    parser.add_argument(
        "--no-adx-filter", action="store_true",
        help="ADX 필터를 끄고 골든크로스마다 매수(원본 피보/역피보 지표 그대로). 기본은 ADX 필터 사용",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    df, crossovers = prepare_data()
    df, crossovers = filter_by_split(df, crossovers, args.split)

    use_adx_filter = not args.no_adx_filter

    print(f"[INFO] 구간: {args.split} ({df['Date'].min().date()} ~ {df['Date'].max().date()})")
    print(f"[INFO] 감지된 교차 지점: {len(crossovers)}건")
    print(f"[INFO] 매수 필터: {f'ADX({ADX_PERIOD}) > {ADX_THRESHOLD}' if use_adx_filter else '미사용(골든크로스마다 매수)'} / "
          f"ADX 약화 시 청산: {'사용' if EXIT_ON_ADX_WEAKEN else '미사용(데드크로스만)'}")

    # 1~2. 백테스트 실행 (골든크로스+ADX 필터 다음날 매수 / 데드크로스(옵션: ADX 약화) 다음날 매도)
    trades_df, open_position, skipped_weak_adx = run_backtest(df, crossovers, use_adx_filter=use_adx_filter)
    print(f"[INFO] ADX 조건 미달로 보류된 골든크로스: {skipped_weak_adx}건")

    # 3. 매매 내역 표
    print("\n[매매 내역]")
    if trades_df.empty:
        print("(완료된 매매 없음)")
    else:
        print(trades_df.to_string(index=False))

    if open_position is not None:
        print(f"\n[참고] 미청산 포지션 존재: 매수일 {open_position['buy_date'].date()}, "
              f"매수가 {open_position['buy_price']:,.0f}원 (데이터 마지막 날까지 매도 신호 없음)")

    # 매매 내역을 CSV로 저장 (완료된 매매가 있을 때만)
    # split/ADX 필터 여부를 번갈아 실행해도 서로 덮어쓰지 않도록 파일명에 반영한다
    suffix = ""
    if args.split != "all":
        suffix += f"_{args.split}"
    if not use_adx_filter:
        suffix += "_noadx"
    output_path = TRADES_OUTPUT_PATH.replace(".csv", f"{suffix}.csv") if suffix else TRADES_OUTPUT_PATH
    if not trades_df.empty:
        trades_df.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"\n[INFO] 매매 내역 저장 완료: {output_path}")

    # 4. 전체 누적 수익률 (완료된 매매만 복리로 반영)
    cumulative_return = compute_cumulative_return(trades_df)
    print(f"\n[전략] 전체 누적 수익률: {cumulative_return:.2f}%")

    # 5. 비교 기준: 매수 후 보유(Buy & Hold) 수익률
    buy_and_hold_return = compute_buy_and_hold_return(df)
    print(f"[비교] 매수 후 보유(Buy & Hold) 수익률: {buy_and_hold_return:.2f}%")


if __name__ == "__main__":
    main()
