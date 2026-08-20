"""
SOXL "추세필터(엔상/엔하 MA17 5일 기울기) + 꼭지/바닥 롤링 매매" 전략 백테스트
(2026-08-20 세션에서 요청받은 새 전략).

[추세필터]
MA17(엔상1선과 동일한 기준선 - 엔하1선은 MA17이 아니라 후행스팬이므로 별개) 5일 기울기 = MA17.diff(5)
- 5일 기울기 > 0 이면 상승추세, < 0 이면 하락추세.

[매수 - 상승추세일 때만, 최대 6유닛(유닛당 최대비중의 1/6)]
- 엔하2(Period=17, ATRPeriod=14, Factor=1) 터치 → 1유닛
- 바닥4(shortPeriod=4, midPeriod=8, longPeriod=16, D1=4) 터치 → 2유닛
- "터치" = 어제는 라인 아래에 있다가 오늘 그 라인 위로 회복한 날
  (기존 backtest_soxl_reserved.py의 Up구름 매수 신호와 동일한 패턴)

[매도 - 하락추세일 때만]
- 엔상2 터치 → 1유닛씩 부분매도
- 꼭지4 터치 → 잔량 전량매도(엔상2 부분매도보다 우선)
- "터치" = 어제는 라인 위에 있다가 오늘 그 라인 아래로 반전한 날
  (기존 backtest_soxl_reserved.py의 S라인 매도 신호와 동일한 패턴)

상승추세 유지 중에는 꼭지 터치가 떠도 매도하지 않는다(홀드) - 매도 조건 자체가
하락추세일 때만 평가되므로 자연히 지켜진다.

체결/자산곡선 모델은 backtest_soxl_reserved.py와 동일하다: 신호는 그날 종가로 확정,
다음 거래일 시가에 체결(수수료 반영), 자산곡선은 오버나이트/장중 구간을 나눠 그날
비중을 곱하는 mark-to-market 방식. "거래" 기록도 매도 체결마다 그 시점까지의
가중평균 매수단가 대비 실현수익률로 남긴다(이동평균법, 부분매도가 반복되므로).
"""

import pandas as pd

import backtest as bt
import backtest_soxl_partial as bsp
import backtest_soxl_reserved as bsr
import ichimoku_custom_indicator as ichi
import kkokji_badak_indicator as kb
import metrics
import up_down_43_indicator as ud43

SOXL_PRICE_PATH = "data/price_SOXL.csv"
RESULTS_PATH = "data/backtest_soxl_trend_rolling.csv"
ATRSTOP_RESULTS_PATH = "data/backtest_soxl_trend_rolling_atrstop.csv"
GINVERSION_RESULTS_PATH = "data/backtest_soxl_trend_rolling_ginversion.csv"

UNIT = 1 / 6         # 유닛당 비중(최대비중 대비) - 최대 6유닛
STEP = 1 / 3         # G역전 진입 시 비중 축소분(최대비중 대비) - backtest_soxl_reserved.py와 동일 비율
MAX_WEIGHT = 1.0

TREND_MA_PERIOD = 17
TREND_SLOPE_DAYS = 5

ATR_STOP_MULTIPLIERS = [3, 4, 5, 6]   # ATR(20)×N 트레일링스탑 후보 배수들 - x3(기존전략과 동일 배수)이
                                       # whipsaw로 신규전략 수익을 갉아먹어서, 더 느슨한 배수도 함께 비교한다
BEAR_PERIOD = ("2022-01-01", "2022-12-31")  # 하락장 방어력만 따로 확인하는 구간(기존 최종전략 비교와 동일 구간)

SWEEP_MULTIPLIERS = [4, 5, 6, 8]   # whipsaw 손실과 하락장 방어 사이의 균형점을 찾기 위한 추가 스윕
SWEEP_RESULTS_PATH = "data/backtest_soxl_trend_rolling_atrsweep.csv"

TOUCH_MODE_RESULTS_PATH = "data/backtest_soxl_trend_rolling_touchmode.csv"


def prepare_data() -> pd.DataFrame:
    """SOXL 가격 데이터를 읽어 엔상/엔하, 꼭지/바닥, 추세(MA17 5일 기울기)를 모두 계산한다."""
    df = pd.read_csv(SOXL_PRICE_PATH)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    df = ichi.add_atr(df)        # ATR(14, TR 단순평균) - 엔상2/엔하2용 (ATRPeriod=14)
    df = ichi.add_en_sang(df)    # 엔상1~5선 (PERIOD=17, FACTOR=1 - 모듈 기본값이 요청 사양과 동일)
    df = ichi.add_en_ha(df)      # 엔하1~5선
    df = kb.add_kkokji_badak(df)  # 꼭지4/바닥4 (sp=4, mp=8, lp=16, D1=4)

    ma17 = df["Close"].rolling(window=TREND_MA_PERIOD).mean()
    df["MA17_5일기울기"] = ma17.diff(TREND_SLOPE_DAYS)

    # ATR(20, TR 단순평균)을 다시 계산해 "ATR" 컬럼을 덮어쓴다 - 트레일링스탑 전용.
    # 엔상2/엔하2 계산에 쓰인 ATR(14)는 이미 위에서 "엔상2선"/"엔하2선" 등 결과 컬럼에
    # 반영이 끝났으므로 덮어써도 안전하다(backtest_soxl_reserved.py의 prepare_data와 동일 관례).
    df = ichi.add_atr(df, period=20)

    # Up구름(Up4/Up5)과 43/-43 일목의 G라인 - G역전(G가 Up구름 상단 위로 역전) 판정용.
    # backtest_soxl_reserved.py의 prepare_data와 동일한 파라미터(p1=25/p2=50/d1=2, p1=50/p2=25/shift=15).
    df = ud43.add_up_down_cloud(df, p1=25, p2=50, d1=2)
    df = ud43.add_43_indicator(df, p1=50, p2=25, shift_days=15)
    return df


def _touch(close_prev: float, close_t: float, line_prev: float, line_t: float, from_above: bool) -> bool:
    """
    "터치" 판정. from_above=True면 전일에는 라인 위(또는 아래 라인이면 반대편)에 있다가
    오늘 그 라인에 닿거나 넘는 "즉시터치"용 방향, from_above=False면 전일에는 반대편에
    있다가 오늘 라인 쪽으로 돌아오는 "터치 후 반대방향 확인"용 방향이다. 두 경우 모두
    라인 값이 NaN(위밍업 부족)이면 False.
    """
    if pd.isna(line_prev) or pd.isna(line_t):
        return False
    if from_above:
        return close_prev > line_prev and close_t <= line_t
    return close_prev < line_prev and close_t >= line_t


def simulate_trend_rolling_strategy(
    df: pd.DataFrame,
    atr_multiplier: float | None = None,
    reduce_on_g_inversion: bool = False,
    immediate_touch: bool = False,
) -> tuple[pd.Series, pd.DataFrame, float, float]:
    """
    일별 mark-to-market 자산곡선(시작=1.0)과 매도 체결마다의 실현수익률 내역을 반환한다.
    뒤의 두 값(total_bought, total_sold)은 "매수로 늘어난 비중 합 - 매도로 줄어든
    비중 합 = 최종 비중"인지 손으로 검증할 수 있도록 함께 반환한다(부분의 합).

    atr_multiplier가 주어지면 ATR(20, TR 단순평균) 트레일링스탑을 추가한다: 포지션을
    보유하는 동안(비중>0) 매일 "매수 이후 종가 기준 최고점"을 갱신하고, 그날 종가가
    (최고종가 - ATR20×배수) 이하로 내려오면 추세/터치 신호와 무관하게 다음 거래일
    시가에 전량 손절한다(backtest_soxl_reserved.py의 ATR 트레일링스탑과 동일한 규칙이며,
    최우선 순위로 다른 매수/매도 신호를 덮어쓴다). df는 prepare_data()로 만든, "ATR"
    컬럼이 ATR(20)으로 채워진 데이터프레임이어야 한다.

    reduce_on_g_inversion=True이면 G역전(G라인이 Up구름 상단 위로 역전) 상태로 "처음
    진입하는 날" 다음 거래일 시가에 비중을 1/3(STEP)만큼 강제로 줄인다(전량매도가 아닌
    부분 축소 - backtest_soxl_reserved.py의 reduce_on_g_inversion과 동일 규칙). 그날의
    다른 매수/매도 신호와 겹치면 함께 반영된다(예: 매수 신호가 같이 뜨면 순증분에서
    1/3을 뺀 만큼만 순매수/순매도). G가 다시 정상(Up구름 아래)으로 돌아와도 축소분을
    자동으로 복구하지 않는다 - 재진입은 기존 매수 신호(엔하2/바닥4 터치)로만 이뤄진다.

    immediate_touch=False(기본)이면 "터치 후 반대방향 확인" 방식을 쓴다: 매수 라인
    (엔하2/바닥4)은 어제 아래에 있다가 오늘 위로 회복해야, 매도 라인(엔상2/꼭지4)은
    어제 위에 있다가 오늘 아래로 반전해야 신호가 뜬다(지금까지의 최종전략과 동일).
    immediate_touch=True이면 "즉시터치" 방식을 쓴다: 방향이 반대로, 매수 라인은 어제
    위에 있다가 오늘 그 이하로 내려오는 순간, 매도 라인은 어제 아래에 있다가 오늘 그
    이상으로 올라오는 순간 바로 신호가 뜬다(반대방향 확인 없이 즉시 체결 예약).
    """
    df = df.sort_values("Date").reset_index(drop=True)
    n = len(df)
    dates = df["Date"].tolist()
    opens = df["Open"].tolist()
    closes = df["Close"].tolist()

    en_ha2 = df["엔하2선"].tolist()
    en_sang2 = df["엔상2선"].tolist()
    badak4 = df["바닥4"].tolist()
    kkokji4 = df["꼭지4"].tolist()
    slope = df["MA17_5일기울기"].tolist()
    if atr_multiplier is not None:
        atr = df["ATR"].tolist()
    if reduce_on_g_inversion:
        g_line = df["G"].tolist()
        up_upper = df[["Up4", "Up5"]].max(axis=1).tolist()
        g_inverted = [
            (pd.notna(g_line[i]) and pd.notna(up_upper[i]) and g_line[i] > up_upper[i])
            for i in range(n)
        ]

    highest_close = None   # 보유 중(비중>0) 매수 이후 종가 기준 최고점 - ATR 트레일링스탑용
    current_weight = 0.0
    avg_cost = 0.0        # 현재 보유분의 가중평균 매수단가(수수료 포함)
    pending_delta = 0.0   # 전날 신호로 예약된, 오늘 시가에 실행할 비중 변화량
    pending_reason = None  # 전날 신호의 매도 사유(ATR스탑/꼭지4 전량매도/엔상2 부분매도) - trades 기록용
    total_bought = 0.0    # 체결된 매수 비중의 누적합(부분)
    total_sold = 0.0      # 체결된 매도 비중의 누적합(부분)

    equity = [1.0] * n
    trades = []

    for t in range(n):
        weight_overnight = current_weight
        delta = pending_delta
        pending_delta = 0.0
        reason = pending_reason
        pending_reason = None
        fee_factor = 1.0

        if delta > 0:
            buy_price = opens[t] * (1 + bt.BUY_FEE_RATE)
            new_weight = min(current_weight + delta, MAX_WEIGHT)
            actual_delta = new_weight - current_weight
            if actual_delta > 1e-9:
                avg_cost = (current_weight * avg_cost + actual_delta * buy_price) / new_weight
                fee_factor = 1 - actual_delta * bt.BUY_FEE_RATE
                total_bought += actual_delta
            current_weight = new_weight
        elif delta < 0:
            sell_price = opens[t] * (1 - bt.SELL_FEE_RATE)
            new_weight = max(current_weight + delta, 0.0)
            actual_delta = current_weight - new_weight
            if actual_delta > 1e-9 and avg_cost > 0:
                realized_return = (sell_price - avg_cost) / avg_cost * 100
                trades.append({
                    "매도일": dates[t],
                    "매도비중": round(actual_delta, 4),
                    "매수평단가": round(avg_cost, 4),
                    "매도가": round(sell_price, 4),
                    "수익률(%)": round(realized_return, 2),
                    "사유": reason,
                })
                fee_factor = 1 - actual_delta * bt.SELL_FEE_RATE
                total_sold += actual_delta
            current_weight = new_weight

        weight_after = current_weight

        if atr_multiplier is not None:
            if weight_after > 0:
                highest_close = closes[t] if highest_close is None else max(highest_close, closes[t])
            else:
                highest_close = None

        if t == 0:
            equity[t] = 1.0
        else:
            overnight_factor = 1 + weight_overnight * (opens[t] / closes[t - 1] - 1)
            intraday_factor = 1 + weight_after * (closes[t] / opens[t] - 1)
            equity[t] = equity[t - 1] * overnight_factor * fee_factor * intraday_factor

        if t == 0:
            continue  # 첫날은 전일 데이터가 없어 신호를 계산할 수 없다

        close_t, close_prev = closes[t], closes[t - 1]

        uptrend = pd.notna(slope[t]) and slope[t] > 0
        downtrend = pd.notna(slope[t]) and slope[t] < 0

        step_delta = 0.0
        sell_kkokji = False
        sell_ensang2 = False

        # 확인방식(기본): 매수는 아래→위로 회복(from_above=False), 매도는 위→아래로 반전(from_above=True).
        # 즉시터치: 방향이 정반대 - 매수는 위→아래로 닿는 순간, 매도는 아래→위로 닿는 순간.
        buy_from_above = immediate_touch
        sell_from_above = not immediate_touch

        if uptrend:
            buy_enha2 = _touch(close_prev, close_t, en_ha2[t - 1], en_ha2[t], buy_from_above)
            buy_badak = _touch(close_prev, close_t, badak4[t - 1], badak4[t], buy_from_above)
            if buy_enha2:
                step_delta += UNIT        # 엔하2 터치 → 1유닛
            if buy_badak:
                step_delta += 2 * UNIT    # 바닥4 터치 → 2유닛

        if downtrend:
            sell_ensang2 = _touch(close_prev, close_t, en_sang2[t - 1], en_sang2[t], sell_from_above)
            sell_kkokji = _touch(close_prev, close_t, kkokji4[t - 1], kkokji4[t], sell_from_above)

        atr_stop = (
            atr_multiplier is not None
            and weight_after > 0
            and highest_close is not None
            and pd.notna(atr[t])
            and close_t <= highest_close - atr[t] * atr_multiplier
        )
        g_inversion_enter = (
            reduce_on_g_inversion and g_inverted[t] and not g_inverted[t - 1]
        )

        if atr_stop:
            base_delta = -current_weight      # ATR 트레일링스탑 손절: 추세/터치 신호와 무관, 최우선
            base_reason = "ATR스탑"
        elif sell_kkokji:
            base_delta = -current_weight      # 꼭지4 터치: 잔량 전량매도
            base_reason = "꼭지4 전량매도"
        elif sell_ensang2:
            base_delta = -UNIT                # 엔상2 터치: 1유닛 부분매도
            base_reason = "엔상2 부분매도"
        else:
            base_delta = step_delta           # 매수(0~3유닛) 또는 무신호(0)
            base_reason = None

        if g_inversion_enter and not atr_stop:
            # G역전 진입: ATR스탑(최우선)이 아닌 한, 그날의 다른 신호에 1/3 비중 축소를 더한다.
            pending_delta = base_delta - STEP
            pending_reason = f"{base_reason}+G역전 비중축소" if base_reason else "G역전 비중축소"
        else:
            pending_delta = base_delta
            pending_reason = base_reason

    equity_series = pd.Series(equity, index=pd.DatetimeIndex(dates))
    trades_df = pd.DataFrame(trades)
    return equity_series, trades_df, total_bought, total_sold


def summarize_strategy(equity: pd.Series, trades_df: pd.DataFrame, label: str) -> dict:
    """승률/평균수익률/중앙값수익률/총수익률/MDD를 계산한다."""
    total_return = (equity.iloc[-1] - 1) * 100
    mdd = bsp.compute_mdd(equity)

    if trades_df.empty:
        win_rate = 0.0
        avg_return = 0.0
        median_return = 0.0
    else:
        win_rate = metrics.calc_win_rate(trades_df)
        avg_return = trades_df["수익률(%)"].mean()
        median_return = trades_df["수익률(%)"].median()

    return {
        "전략": label,
        "매도체결건수": len(trades_df),
        "승률(%)": round(win_rate, 2),
        "평균수익률(%)": round(avg_return, 2),
        "중앙값수익률(%)": round(median_return, 2),
        "총수익률(%)": round(total_return, 2),
        "MDD(%)": round(mdd, 2),
    }


def summarize_period(equity: pd.Series, trades_df: pd.DataFrame, label: str, start: str, end: str) -> dict:
    """
    equity/trades_df를 [start, end] 구간만 잘라 summarize_strategy와 같은 지표를 다시 계산한다.
    자산곡선은 구간 시작일 값을 1.0으로 재정규화해서(그 시점까지 쌓인 포지션은 그대로
    이어받되, 총수익률/MDD는 그 시점부터 다시 잰다) 그 구간만의 방어력을 보여준다
    (backtest_soxl_reserved.py의 compute_period_metrics와 같은 방식).
    """
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    equity_sub = equity[(equity.index >= start_ts) & (equity.index <= end_ts)]
    if equity_sub.empty:
        row = summarize_strategy(pd.Series([1.0]), pd.DataFrame(), label)
        row["구간"] = f"{start}~{end}(데이터 없음)"
        return row
    equity_norm = equity_sub / equity_sub.iloc[0]

    if trades_df.empty:
        trades_sub = trades_df
    else:
        sell_dates = pd.to_datetime(trades_df["매도일"])
        trades_sub = trades_df[(sell_dates >= start_ts) & (sell_dates <= end_ts)]

    row = summarize_strategy(equity_norm, trades_sub, label)
    row["구간"] = f"{equity_sub.index.min().date()} ~ {equity_sub.index.max().date()}"
    return row


def summarize_sweep_row(equity: pd.Series, trades_df: pd.DataFrame, label: str) -> dict:
    """
    총수익률/MDD/Calmar(총수익률/|MDD|)와 함께, "사유" 컬럼으로 ATR스탑 청산 건만 따로 떼서
    건수와 평균수익률(=평균손실, 음수면 손실)을 계산한다. whipsaw 손실과 하락장 방어 사이의
    균형점을 찾기 위한 ATR 배수 스윕용 요약이다.
    """
    total_return = (equity.iloc[-1] - 1) * 100
    mdd = bsp.compute_mdd(equity)
    calmar = total_return / abs(mdd) if mdd != 0 else float("inf")

    if trades_df.empty:
        sell_count = 0
        atr_stop_count = 0
        atr_stop_avg_return = None
    else:
        sell_count = len(trades_df)
        if "사유" in trades_df.columns:
            atr_stop_trades = trades_df[trades_df["사유"] == "ATR스탑"]
        else:
            atr_stop_trades = trades_df.iloc[0:0]
        atr_stop_count = len(atr_stop_trades)
        atr_stop_avg_return = round(atr_stop_trades["수익률(%)"].mean(), 2) if atr_stop_count > 0 else None

    return {
        "전략": label,
        "매도체결건수": sell_count,
        "ATR스탑청산건수": atr_stop_count,
        "ATR스탑평균수익률(%)": atr_stop_avg_return,
        "총수익률(%)": round(total_return, 2),
        "MDD(%)": round(mdd, 2),
        "Calmar(총수익률/|MDD|)": round(calmar, 2) if calmar != float("inf") else calmar,
    }


def summarize_calmar_row(equity: pd.Series, trades_df: pd.DataFrame, label: str) -> dict:
    """총수익률/MDD/Calmar(총수익률/|MDD|)만 계산한다 - G역전 비중축소 비교용 간단 요약."""
    total_return = (equity.iloc[-1] - 1) * 100
    mdd = bsp.compute_mdd(equity)
    calmar = total_return / abs(mdd) if mdd != 0 else float("inf")
    return {
        "전략": label,
        "매도체결건수": len(trades_df),
        "총수익률(%)": round(total_return, 2),
        "MDD(%)": round(mdd, 2),
        "Calmar(총수익률/|MDD|)": round(calmar, 2) if calmar != float("inf") else calmar,
    }


def summarize_full_row(equity: pd.Series, trades_df: pd.DataFrame, label: str) -> dict:
    """summarize_strategy(승률/평균/중앙값/총수익률/MDD)에 Calmar까지 더한 전체 요약."""
    row = summarize_strategy(equity, trades_df, label)
    mdd = row["MDD(%)"]
    calmar = row["총수익률(%)"] / abs(mdd) if mdd != 0 else float("inf")
    row["Calmar(총수익률/|MDD|)"] = round(calmar, 2) if calmar != float("inf") else calmar
    return row


def run_atr_sweep(df: pd.DataFrame, equity_baseline: pd.Series, trades_baseline: pd.DataFrame) -> pd.DataFrame:
    """
    ATR 배수를 SWEEP_MULTIPLIERS(4/5/6/8)로 스윕해, whipsaw 손실과 하락장 방어 사이의
    균형점을 찾기 위한 비교표를 만든다. 스탑 없음(기준선)도 함께 포함한다.
    """
    rows = [summarize_sweep_row(equity_baseline, trades_baseline, "스탑없음(기준선)")]
    for multiplier in SWEEP_MULTIPLIERS:
        equity_m, trades_m, bought_m, sold_m = simulate_trend_rolling_strategy(df, atr_multiplier=multiplier)
        implied_m = bought_m - sold_m
        print(
            f"[검증(ATR x{multiplier}스탑)] 매수비중합({bought_m:.4f}) - "
            f"매도비중합({sold_m:.4f}) = {implied_m:.4f}"
        )
        rows.append(summarize_sweep_row(equity_m, trades_m, f"ATR x{multiplier}스탑"))
    return pd.DataFrame(rows)


def main():
    df = prepare_data()
    print(f"[INFO] SOXL 데이터 구간: {df['Date'].min().date()} ~ {df['Date'].max().date()} ({len(df)}거래일)")

    equity, trades_df, total_bought, total_sold = simulate_trend_rolling_strategy(df)

    # 손 계산 검증(부분의 합 = 전체): 체결된 매수 비중 합 - 매도 비중 합이
    # 마지막 날 실제 보유비중과 일치해야 한다. 또한 매도비중 합은 trades_df의
    # "매도비중" 컬럼 합과 같아야 한다(같은 값을 두 경로로 계산해 비교).
    implied_final_weight = total_bought - total_sold
    trades_sold_sum = trades_df["매도비중"].sum() if not trades_df.empty else 0.0
    print(f"[검증] 매수비중합({total_bought:.4f}) - 매도비중합({total_sold:.4f}) = {implied_final_weight:.4f}")
    print(f"[검증] trades_df 매도비중 합계 일치 여부: {trades_sold_sum:.4f} == {total_sold:.4f}")

    row_new = summarize_strategy(equity, trades_df, "추세필터+꼭지바닥 롤링매매(신규)")

    # 기존 최종전략: G역전 1/3축소 + ATR스탑(x3) 결합
    df_reserved = bsr.prepare_data()
    equity_final, trades_final, _ = bsr.simulate_reserved_strategy(
        df_reserved, reduce_on_g_inversion=True, atr_multiplier=3
    )
    row_final = summarize_strategy(equity_final, trades_final, "기존 최종전략(G역전1/3축소+ATR x3스탑)")

    result_df = pd.DataFrame([row_new, row_final])
    print("\n[비교: 추세필터+꼭지바닥 롤링매매 vs 기존 최종전략]")
    print(result_df.to_string(index=False))

    result_df.to_csv(RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n[INFO] 결과 저장 완료: {RESULTS_PATH}")

    # --- ATR(20)xN 트레일링스탑을 얹은 변형들: 매수/매도(터치) 로직은 신규전략과 동일하고,
    # 보유 중 최고종가 대비 -ATR20xN 하락 시 추세/터치 신호와 무관하게 전량 손절만 추가된다.
    # x3(기존 최종전략과 동일 배수)이 whipsaw로 수익을 갉아먹어서, 더 느슨한 배수(4~6)도 같이 본다.
    full_rows = [row_new]
    bear_rows = [summarize_period(equity, trades_df, "추세필터+꼭지바닥 롤링매매(신규)", *BEAR_PERIOD)]

    for multiplier in ATR_STOP_MULTIPLIERS:
        label = f"추세필터+꼭지바닥 롤링매매 + ATR x{multiplier}스탑"
        equity_stop, trades_stop, total_bought_stop, total_sold_stop = simulate_trend_rolling_strategy(
            df, atr_multiplier=multiplier
        )
        implied_final_weight_stop = total_bought_stop - total_sold_stop
        print(
            f"\n[검증(ATR x{multiplier}스탑)] 매수비중합({total_bought_stop:.4f}) - "
            f"매도비중합({total_sold_stop:.4f}) = {implied_final_weight_stop:.4f}"
        )
        full_rows.append(summarize_strategy(equity_stop, trades_stop, label))
        bear_rows.append(summarize_period(equity_stop, trades_stop, label, *BEAR_PERIOD))

    full_rows.append(row_final)
    bear_rows.append(summarize_period(equity_final, trades_final, "기존 최종전략(G역전1/3축소+ATR x3스탑)", *BEAR_PERIOD))

    for row in full_rows:
        row["구간"] = "전체기간(2010~2026)"

    col_order = ["전략", "구간", "매도체결건수", "승률(%)", "평균수익률(%)", "중앙값수익률(%)", "총수익률(%)", "MDD(%)"]
    atrstop_df = pd.DataFrame(full_rows + bear_rows)[col_order]

    print(f"\n[비교: 신규전략 vs ATR x{{{','.join(map(str, ATR_STOP_MULTIPLIERS))}}}스탑 vs 기존 최종전략 (전체기간 + 2022년 하락장)]")
    print(atrstop_df.to_string(index=False))

    atrstop_df.to_csv(ATRSTOP_RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n[INFO] 결과 저장 완료: {ATRSTOP_RESULTS_PATH}")

    # --- ATR 배수 스윕(x4/x5/x6/x8): whipsaw 손실과 하락장 방어 사이의 균형점을 찾는다.
    # 매도 사유(ATR스탑 vs 엔상2/꼭지4 정상매도)를 나눠서, ATR스탑으로 청산된 거래의
    # 건수와 평균수익률(평균손실)을 따로 본다.
    sweep_df = run_atr_sweep(df, equity, trades_df)
    print(f"\n[ATR 배수 스윕(x{','.join(map(str, SWEEP_MULTIPLIERS))}) - whipsaw 손실 vs 하락장 방어 균형점 탐색]")
    print(sweep_df.to_string(index=False))

    sweep_df.to_csv(SWEEP_RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n[INFO] 결과 저장 완료: {SWEEP_RESULTS_PATH}")

    # --- G역전(G라인이 Up구름 상단 위로 역전) 1/3 비중축소를 얹은 변형: 매수/매도(터치)
    # 로직은 신규전략과 동일하고, G역전 진입 시 전량매도가 아닌 1/3만 축소한다(복구는
    # 자동으로 하지 않고, 기존 매수 신호로만 재진입).
    equity_ginv, trades_ginv, total_bought_ginv, total_sold_ginv = simulate_trend_rolling_strategy(
        df, reduce_on_g_inversion=True
    )
    implied_ginv = total_bought_ginv - total_sold_ginv
    print(f"\n[검증(G역전 비중축소)] 매수비중합({total_bought_ginv:.4f}) - 매도비중합({total_sold_ginv:.4f}) = {implied_ginv:.4f}")

    # --- G역전1/3축소 + ATR x6스탑 결합: ATR스탑이 최우선(전량 손절)이고, G역전 축소는
    # ATR스탑이 뜨지 않은 날에만 그날의 다른 신호 위에 1/3을 추가로 뺀다(위 함수 docstring 참고).
    equity_combo, trades_combo, total_bought_combo, total_sold_combo = simulate_trend_rolling_strategy(
        df, atr_multiplier=6, reduce_on_g_inversion=True
    )
    implied_combo = total_bought_combo - total_sold_combo
    print(
        f"\n[검증(G역전1/3축소+ATR x6스탑)] 매수비중합({total_bought_combo:.4f}) - "
        f"매도비중합({total_sold_combo:.4f}) = {implied_combo:.4f}"
    )

    ginversion_df = pd.DataFrame([
        summarize_calmar_row(equity, trades_df, "스탑없음(기준선)"),
        summarize_calmar_row(equity_ginv, trades_ginv, "추세필터+꼭지바닥 롤링매매 + G역전1/3축소"),
        summarize_calmar_row(equity_combo, trades_combo, "추세필터+꼭지바닥 롤링매매 + G역전1/3축소 + ATR x6스탑"),
    ])
    print("\n[비교: 스탑없음(기준선) vs G역전1/3축소 vs G역전1/3축소+ATR x6스탑]")
    print(ginversion_df.to_string(index=False))

    ginversion_df.to_csv(GINVERSION_RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n[INFO] 결과 저장 완료: {GINVERSION_RESULTS_PATH}")

    # --- "즉시터치" vs "터치 후 반대방향 확인"(기존 채택 방식) 비교. 기준선(G역전 없음)과
    # 최종전략(G역전1/3축소) 두 구성 각각에서 터치 방식만 바꿔본다.
    equity_imm, trades_imm, total_bought_imm, total_sold_imm = simulate_trend_rolling_strategy(
        df, immediate_touch=True
    )
    implied_imm = total_bought_imm - total_sold_imm
    print(f"\n[검증(즉시터치, 기준선)] 매수비중합({total_bought_imm:.4f}) - 매도비중합({total_sold_imm:.4f}) = {implied_imm:.4f}")

    equity_imm_ginv, trades_imm_ginv, total_bought_imm_ginv, total_sold_imm_ginv = simulate_trend_rolling_strategy(
        df, reduce_on_g_inversion=True, immediate_touch=True
    )
    implied_imm_ginv = total_bought_imm_ginv - total_sold_imm_ginv
    print(
        f"\n[검증(즉시터치+G역전1/3축소)] 매수비중합({total_bought_imm_ginv:.4f}) - "
        f"매도비중합({total_sold_imm_ginv:.4f}) = {implied_imm_ginv:.4f}"
    )

    touchmode_df = pd.DataFrame([
        summarize_full_row(equity, trades_df, "확인방식(기준선)"),
        summarize_full_row(equity_imm, trades_imm, "즉시터치(기준선)"),
        summarize_full_row(equity_ginv, trades_ginv, "확인방식 + G역전1/3축소(최종전략)"),
        summarize_full_row(equity_imm_ginv, trades_imm_ginv, "즉시터치 + G역전1/3축소"),
    ])
    print("\n[비교: 확인방식 vs 즉시터치 (기준선 / G역전1/3축소 각각)]")
    print(touchmode_df.to_string(index=False))

    touchmode_df.to_csv(TOUCH_MODE_RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n[INFO] 결과 저장 완료: {TOUCH_MODE_RESULTS_PATH}")


if __name__ == "__main__":
    main()
