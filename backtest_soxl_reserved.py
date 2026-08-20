"""
SOXL "43/-43 + Up/Down 구름 예약매수" 전략 백테스트 (2026-08-20 세션에서 최종 확정한 버전).

실전에서 쓰던 분할매수/분할매도(각 2단계) 방식을 그대로 시뮬레이션한다:

[매수 - 분할 2단계, 각 1/3 비중]
1차 매수: 종가가 Up구름 하단 아래로 찍었다가 다시 위로 올라오면(지지 후 반등)
2차 매수: 종가가 G라인(43/-43 일목, 15일 선행shift) 아래로 이탈했다가 다시 위로 회복하면
※ 비중이 최대(100%)에 도달하면 추가매수 중단

[매도 - 분할 2단계, 각 1/3 비중]
1차 매도: 종가가 Down구름 위로 돌파하면
2차 매도: 종가가 S라인(43/-43 일목, 15일 선행shift) 위로 돌파했다가 다시 아래로 내려오면
※ 비중이 0%에 도달하면 더 팔 물량 없음(대기)

[롤링]: 위 매수/매도 신호는 시장이 오르내리는 동안 반복해서 뜨며, 한 사이클로 끝나지 않는다.

포지션 크기 환산: 실전에서는 "각 20~30주, 최대 60~70주"처럼 절대 주식수로 관리하지만, SOXL은
2010년 $0.66 -> 2026년 $150대까지 200배 넘게 올라서 절대 주식수를 16년 전체 구간에 그대로
적용할 수 없다. 대신 "다리(leg)당 최대비중의 1/3씩" 비중(%)으로 환산했다(3다리를 다 채우면
100% - 20~30주/60~70주 비율의 중간값 근사). "보유량이 0에 가까워지면 현금 15~20% 유지" 규칙은
SOXL 단일종목 비중 시뮬레이션에서는 비중 0%가 이미 현금 100%를 뜻해 반영할 대상이 없다(포트폴리오
전체 배분에 대한 지침으로 보고 이 백테스트에서는 별도 반영하지 않았다).

체결/자산곡선 모델은 backtest_soxl_partial.py와 같다: 신호는 그날 종가로 확정, 다음 거래일 시가에
체결(수수료 반영), 자산곡선은 매일 오버나이트(전일 종가~당일 시가)/장중(당일 시가~종가) 구간을
나눠 그날 비중을 곱해 반영하는 mark-to-market 방식이다. 승률/손익비 계산을 위한 "거래"는 매도
체결마다, 그 시점까지의 가중평균 매수단가 대비 실현수익률로 기록한다(부분매도가 반복되는 전략이라
전량매수/전량매도 짝짓기가 아니라 회계상 이동평균법을 썼다).
"""

import pandas as pd

import backtest as bt
import backtest_soxl_partial as bsp
import ichimoku_custom_indicator as ichi
import metrics
import up_down_43_indicator as ud43

SOXL_PRICE_PATH = "data/price_SOXL.csv"
RESULTS_PATH = "data/backtest_results_soxl_reserved.csv"
PARTIAL_RESULTS_PATH = "data/backtest_results_soxl_partial.csv"

STEP = 1 / 3       # 다리(leg)당 비중 증감분(최대비중 대비)
MAX_WEIGHT = 1.0


def prepare_data() -> pd.DataFrame:
    """SOXL 가격 데이터를 읽어 Up/Down구름 + 43/-43(S/G 포함) 지표를 모두 계산한다."""
    df = pd.read_csv(SOXL_PRICE_PATH)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    df = ud43.add_up_down_cloud(df, p1=25, p2=50, d1=2)
    df = ud43.add_43_indicator(df, p1=50, p2=25, shift_days=15)
    df = ichi.add_senkou_spans(df)  # 선1/선2(양운/음운) - regime_guard용, 기존 프로젝트 지표 그대로 재사용
    df = ichi.add_atr(df, period=20)  # ATR(20, TR 단순평균) - ATR 트레일링스탑용. "ATR" 컬럼으로 추가됨
    return df


def simulate_reserved_strategy(
    df: pd.DataFrame,
    regime_guard: bool = False,
    block_buy_in_bear: bool = False,
    block_buy_on_g_inversion: bool = False,
    reduce_on_g_inversion: bool = False,
    atr_multiplier: float | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """
    일별 mark-to-market 자산곡선(시작=1.0)과, 매도 체결마다의 실현수익률 내역을 반환한다.

    regime_guard=True이면, 4개 분할매수/매도 신호와 별개로 "양운(선1>선2)이 음운으로
    전환되는 날" 다음 거래일 시가에 남은 포지션을 전량(1/3 단위가 아니라 100%) 강제청산한다
    (2022년처럼 반등 없이 계속 밀리는 급락장에 대한 방어선을 추가하기 위한 옵션).

    block_buy_in_bear=True이면, 추가로 음운 구간(선1<선2)에는 1차/2차 매수 신호가 떠도
    무시한다. regime_guard만 켜면 "전환되는 순간"에만 청산하고 그 뒤 음운이 계속되는
    동안에도 눌림목 매수 신호가 뜨면 그대로 다시 사들이기 때문에(실제로 2022년에 이렇게
    되돌아 들어갔다가 더 크게 물렸다), 방어 효과를 제대로 보려면 이 옵션을 같이 켜야 한다.

    G라인 역전(analyze_g_inversion_event.py에서 검증한, G > Up구름 상단 상태) 관련 옵션:
    - block_buy_on_g_inversion=True: 역전 상태(G > Up구름 상단)가 지속되는 동안 1차/2차
      매수 신호를 무시한다("매수 신호 무시").
    - reduce_on_g_inversion=True: 역전 상태로 "처음 진입하는 날" 다음 거래일 시가에
      비중을 1/3(STEP) 만큼 강제로 줄인다("포지션 비중 축소" - regime_guard의 전량청산과
      달리 부분 축소다).

    atr_multiplier가 주어지면 ATR(20, TR 단순평균) 트레일링스탑을 추가한다: 포지션을
    보유하는 동안(비중>0) 매일 "매수 이후 종가 기준 최고점"을 갱신하고, 그날 종가가
    (최고종가 - ATR20×배수) 이하로 내려오면 다른 신호와 무관하게 다음 거래일 시가에
    전량 손절한다(우선순위 최상위 - regime_guard/g_inversion보다 먼저 적용).
    """
    df = df.sort_values("Date").reset_index(drop=True)
    n = len(df)
    dates = df["Date"].tolist()
    opens = df["Open"].tolist()
    closes = df["Close"].tolist()

    up_lower = df[["Up4", "Up5"]].min(axis=1).tolist()
    up_upper = df[["Up4", "Up5"]].max(axis=1).tolist()
    down_upper = df[["Down4", "Down5"]].max(axis=1).tolist()
    s_line = df["S"].tolist()
    g_line = df["G"].tolist()

    if regime_guard or block_buy_in_bear:
        bull = (df["선1"] > df["선2"]).tolist()
        bull_valid = (df["선1"].notna() & df["선2"].notna()).tolist()

    if block_buy_on_g_inversion or reduce_on_g_inversion:
        g_inverted = [
            (pd.notna(g_line[i]) and pd.notna(up_upper[i]) and g_line[i] > up_upper[i])
            for i in range(n)
        ]

    if atr_multiplier is not None:
        atr = df["ATR"].tolist()

    current_weight = 0.0
    avg_cost = 0.0          # 현재 보유분의 가중평균 매수단가(수수료 포함)
    pending_delta = 0.0     # 전날 신호로 예약된, 오늘 시가에 실행할 비중 변화량
    highest_close = None    # 보유 중(비중>0) 매수 이후 종가 기준 최고점 - ATR 트레일링스탑용

    equity = [1.0] * n
    trades = []

    for t in range(n):
        weight_overnight = current_weight
        delta = pending_delta
        pending_delta = 0.0
        fee_notional = 0.0
        fee_factor = 1.0

        if delta > 0:
            buy_price = opens[t] * (1 + bt.BUY_FEE_RATE)
            new_weight = min(current_weight + delta, MAX_WEIGHT)
            actual_delta = new_weight - current_weight
            if actual_delta > 1e-9:
                avg_cost = (current_weight * avg_cost + actual_delta * buy_price) / new_weight
                fee_notional = actual_delta
                fee_factor = 1 - fee_notional * bt.BUY_FEE_RATE
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
                })
                fee_notional = actual_delta
                fee_factor = 1 - fee_notional * bt.SELL_FEE_RATE
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

        if t == 0 or t == n - 1:
            continue  # 첫날은 전일 데이터가 없고, 마지막 날은 "다음날 시가"가 없어 신호를 실행할 수 없다

        close_t, close_prev = closes[t], closes[t - 1]
        up_t, up_prev = up_lower[t], up_lower[t - 1]
        down_t, down_prev = down_upper[t], down_upper[t - 1]
        s_t, s_prev = s_line[t], s_line[t - 1]
        g_t, g_prev = g_line[t], g_line[t - 1]

        buy_allowed = (not block_buy_in_bear) or (bull_valid[t] and bull[t])
        if block_buy_on_g_inversion and g_inverted[t]:
            buy_allowed = False

        step_delta = 0.0
        if buy_allowed and pd.notna(up_t) and pd.notna(up_prev) and close_prev < up_prev and close_t >= up_t:
            step_delta += STEP   # 1차 매수: Up구름 하단 지지 후 반등
        if buy_allowed and pd.notna(g_t) and pd.notna(g_prev) and close_prev < g_prev and close_t >= g_t:
            step_delta += STEP   # 2차 매수: G라인 이탈 후 회복
        if pd.notna(down_t) and pd.notna(down_prev) and close_prev < down_prev and close_t >= down_t:
            step_delta -= STEP   # 1차 매도: Down구름 상향 돌파
        if pd.notna(s_t) and pd.notna(s_prev) and close_prev > s_prev and close_t <= s_t:
            step_delta -= STEP   # 2차 매도: S라인 돌파 후 재하락

        forced_exit = (
            regime_guard
            and bull_valid[t] and bull_valid[t - 1]
            and bull[t - 1] and not bull[t]
        )
        g_inversion_enter = (
            reduce_on_g_inversion and g_inverted[t] and not g_inverted[t - 1]
        )
        atr_stop = (
            atr_multiplier is not None
            and weight_after > 0
            and highest_close is not None
            and pd.notna(atr[t])
            and close_t <= highest_close - atr[t] * atr_multiplier
        )

        if atr_stop:
            pending_delta = -current_weight   # ATR 트레일링스탑: 전량 손절, 최우선 순위
        elif forced_exit:
            pending_delta = -current_weight   # 전량 강제청산
        elif g_inversion_enter:
            pending_delta = step_delta - STEP   # 평소 신호에 더해 비중 1/3 추가 축소(실행 시 0 아래로는 클립됨)
        else:
            pending_delta = step_delta

    equity_series = pd.Series(equity, index=pd.DatetimeIndex(dates))
    trades_df = pd.DataFrame(trades)
    return equity_series, trades_df


def summarize_strategy(df: pd.DataFrame, equity: pd.Series, trades_df: pd.DataFrame, label: str) -> dict:
    total_return = (equity.iloc[-1] - 1) * 100
    mdd = bsp.compute_mdd(equity)
    cagr = bsp.compute_cagr(equity)
    calmar = cagr / abs(mdd) if mdd != 0 else float("inf")

    bh_equity = bsp.compute_buy_and_hold_equity(df)
    bh_total_return = (bh_equity.iloc[-1] - 1) * 100
    capture_pct = total_return / bh_total_return * 100 if bh_total_return != 0 else 0.0

    win_rate = metrics.calc_win_rate(trades_df) if not trades_df.empty else 0.0
    pl_ratio = metrics.calc_profit_loss_ratio(trades_df) if not trades_df.empty else 0.0

    return {
        "전략": label,
        "매도체결건수": len(trades_df),
        "승률(%)": round(win_rate, 2),
        "손익비": round(pl_ratio, 2),
        "총수익률(%)": round(total_return, 2),
        "MDD(%)": round(mdd, 2),
        "CAGR(%)": round(cagr, 2),
        "BuyHold대비포착률(%)": round(capture_pct, 2),
        "Calmar(CAGR/|MDD|)": round(calmar, 2),
    }


def compute_period_metrics(
    equity: pd.Series, trades_df: pd.DataFrame, start_date: str, end_date: str | None = None,
) -> dict:
    """
    equity/trades_df를 [start_date, end_date] 구간만 잘라 승률/손익비/총수익률/MDD를 다시 계산한다.
    자산곡선은 구간 시작일 값을 1.0으로 재정규화해서(그 시점까지 쌓인 포지션은 그대로 이어받되,
    총수익률/MDD는 그 시점부터 다시 잰다), 그 시점부터 실제로 이 전략을 계속 따라갔다면
    경험했을 성과를 보여준다.
    """
    start = pd.Timestamp(start_date)
    equity_sub = equity[equity.index >= start]
    if end_date is not None:
        equity_sub = equity_sub[equity_sub.index <= pd.Timestamp(end_date)]
    if equity_sub.empty:
        return {}
    equity_norm = equity_sub / equity_sub.iloc[0]

    trades_sub = trades_df[pd.to_datetime(trades_df["매도일"]) >= start] if not trades_df.empty else trades_df
    if end_date is not None and not trades_sub.empty:
        trades_sub = trades_sub[pd.to_datetime(trades_sub["매도일"]) <= pd.Timestamp(end_date)]

    total_return = (equity_norm.iloc[-1] - 1) * 100
    mdd = bsp.compute_mdd(equity_norm)
    win_rate = metrics.calc_win_rate(trades_sub) if not trades_sub.empty else 0.0
    pl_ratio = metrics.calc_profit_loss_ratio(trades_sub) if not trades_sub.empty else 0.0

    return {
        "구간": f"{equity_sub.index.min().date()} ~ {equity_sub.index.max().date()}",
        "매도체결건수": len(trades_sub),
        "승률(%)": round(win_rate, 2),
        "손익비": round(pl_ratio, 2),
        "총수익률(%)": round(total_return, 2),
        "MDD(%)": round(mdd, 2),
    }


FINAL_COMPARISON_PATH = "data/backtest_soxl_final_comparison.csv"
FINAL_COMPARISON_PERIOD = ("2022-01-01", "2022-12-31")


def run_final_comparison(df: pd.DataFrame) -> pd.DataFrame:
    """
    ATR(20, TR 단순평균) 트레일링스탑(배수 2/3/4)을, 기존 전략 및 G역전 1/3 축소와
    전체기간+2022년 하락장 구간 각각에서 비교한다. ATR 스탑 조건은 "오늘 종가 <=
    (매수 이후 종가 기준 최고점 - ATR20×배수)"이면 다음 거래일 시가에 전량 손절(다른
    신호와 무관, 최우선 순위)이다.
    """
    variants = [
        ("기존(가드 없음)", {}),
        ("G역전 1/3 축소", {"reduce_on_g_inversion": True}),
        ("ATR스탑(x2) 단독", {"atr_multiplier": 2}),
        ("ATR스탑(x3) 단독", {"atr_multiplier": 3}),
        ("ATR스탑(x4) 단독", {"atr_multiplier": 4}),
        ("G역전 1/3축소 + ATR스탑(x3) 결합", {"reduce_on_g_inversion": True, "atr_multiplier": 3}),
    ]

    rows = []
    for label, kwargs in variants:
        equity, trades_df = simulate_reserved_strategy(df, **kwargs)

        full_row = summarize_strategy(df, equity, trades_df, label)
        full_row["구간"] = "전체기간(2010~2026)"
        rows.append(full_row)

        period_row = compute_period_metrics(equity, trades_df, *FINAL_COMPARISON_PERIOD)
        period_row = {"전략": label, "구간": "2022년 하락장", **period_row}
        rows.append(period_row)

    result_df = pd.DataFrame(rows)
    col_order = [
        "전략", "구간", "매도체결건수", "승률(%)", "손익비", "총수익률(%)", "MDD(%)",
        "CAGR(%)", "BuyHold대비포착률(%)", "Calmar(CAGR/|MDD|)",
    ]
    result_df = result_df[[c for c in col_order if c in result_df.columns]]

    print("\n[최종 비교: 기존 vs G역전1/3축소 vs ATR트레일링스탑(x2/x3/x4) vs 결합]")
    print(result_df.to_string(index=False))

    result_df.to_csv(FINAL_COMPARISON_PATH, index=False, encoding="utf-8-sig")
    print(f"\n[INFO] 최종 비교 결과 저장 완료: {FINAL_COMPARISON_PATH}")
    return result_df


def main():
    df = prepare_data()
    print(f"[INFO] SOXL 데이터 구간: {df['Date'].min().date()} ~ {df['Date'].max().date()} ({len(df)}거래일)")

    run_final_comparison(df)

    equity, trades_df = simulate_reserved_strategy(df, regime_guard=False)
    equity_guard, trades_df_guard = simulate_reserved_strategy(df, regime_guard=True)
    equity_guard2, trades_df_guard2 = simulate_reserved_strategy(
        df, regime_guard=True, block_buy_in_bear=True
    )
    equity_g_block, trades_g_block = simulate_reserved_strategy(
        df, block_buy_on_g_inversion=True
    )
    equity_g_reduce, trades_g_reduce = simulate_reserved_strategy(
        df, reduce_on_g_inversion=True
    )

    rows = [
        summarize_strategy(df, equity, trades_df, "43/-43+Up/Down 예약매수(기존)"),
        summarize_strategy(df, equity_guard, trades_df_guard, "예약매수(강제청산 가드만)"),
        summarize_strategy(df, equity_guard2, trades_df_guard2, "예약매수(강제청산 가드+음운 매수차단)"),
        summarize_strategy(df, equity_g_block, trades_g_block, "예약매수(G역전 시 매수신호 무시)"),
        summarize_strategy(df, equity_g_reduce, trades_g_reduce, "예약매수(G역전 시 비중 1/3 축소)"),
    ]

    print("\n[전체기간(2010~2026) 비교: 기존 vs 가드/필터 변형들]")
    print(pd.DataFrame(rows).to_string(index=False))

    # 2022년 하락장만 잘라 각 변형의 방어력을 비교
    print("\n[2022년 하락장만 재계산 - 각 변형 비교]")
    period_2022 = []
    for label, eq, tr in [
        ("기존(가드 없음)", equity, trades_df),
        ("강제청산 가드만", equity_guard, trades_df_guard),
        ("강제청산+음운 매수차단", equity_guard2, trades_df_guard2),
        ("G역전 시 매수신호 무시", equity_g_block, trades_g_block),
        ("G역전 시 비중 1/3 축소", equity_g_reduce, trades_g_reduce),
    ]:
        stats = compute_period_metrics(eq, tr, "2022-01-01", "2022-12-31")
        period_2022.append({"전략": label, **stats})
    print(pd.DataFrame(period_2022).to_string(index=False))

    # 2024-05-01 이후 구간만 잘라 재계산 (실제 $5,000 -> $14,000(+180%) 거둔 기간과 비교용)
    PERIOD_START = "2024-05-01"
    period_stats = compute_period_metrics(equity, trades_df, PERIOD_START)
    print(f"\n[{PERIOD_START} 이후 구간만 재계산 - 기존(가드 없음) 전략]")
    for k, v in period_stats.items():
        print(f"  {k}: {v}")

    try:
        partial_df = pd.read_csv(PARTIAL_RESULTS_PATH, encoding="utf-8-sig")
        partial_30 = partial_df[partial_df["음운비중(%)"] == 30].iloc[0]
        rows.append({
            "전략": "부분비중(음운 30% 유지)",
            "매도체결건수": None,
            "승률(%)": None,
            "손익비": None,
            "총수익률(%)": partial_30["총수익률(%)"],
            "MDD(%)": partial_30["MDD(%)"],
            "CAGR(%)": partial_30["CAGR(%)"],
            "BuyHold대비포착률(%)": partial_30["BuyHold대비포착률(%)"],
            "Calmar(CAGR/|MDD|)": partial_30["Calmar(CAGR/|MDD|)"],
        })
        bh_row = partial_df[partial_df["시나리오"] == "Buy&Hold(참고)"].iloc[0]
        rows.append({
            "전략": "Buy&Hold(참고)",
            "매도체결건수": None,
            "승률(%)": None,
            "손익비": None,
            "총수익률(%)": bh_row["총수익률(%)"],
            "MDD(%)": bh_row["MDD(%)"],
            "CAGR(%)": bh_row["CAGR(%)"],
            "BuyHold대비포착률(%)": bh_row["BuyHold대비포착률(%)"],
            "Calmar(CAGR/|MDD|)": bh_row["Calmar(CAGR/|MDD|)"],
        })
    except FileNotFoundError:
        print(f"\n[WARN] {PARTIAL_RESULTS_PATH}가 없어 부분비중(30%) 비교는 건너뜁니다.")

    comparison_df = pd.DataFrame(rows)
    print("\n[부분비중(30%) / Buy&Hold와 비교]")
    print(comparison_df.to_string(index=False))

    comparison_df.to_csv(RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n[INFO] 결과 저장 완료: {RESULTS_PATH}")

    if not trades_df.empty:
        trades_path = "data/backtest_trades_soxl_reserved.csv"
        trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")
        print(f"[INFO] 매도 체결 내역 저장 완료: {trades_path}")

    if not trades_df_guard.empty:
        guard_trades_path = "data/backtest_trades_soxl_reserved_guard.csv"
        trades_df_guard.to_csv(guard_trades_path, index=False, encoding="utf-8-sig")
        print(f"[INFO] 강제청산 가드 버전 매도 체결 내역 저장 완료: {guard_trades_path}")

    if not trades_g_block.empty:
        trades_g_block.to_csv(
            "data/backtest_trades_soxl_reserved_g_block.csv", index=False, encoding="utf-8-sig"
        )
    if not trades_g_reduce.empty:
        trades_g_reduce.to_csv(
            "data/backtest_trades_soxl_reserved_g_reduce.csv", index=False, encoding="utf-8-sig"
        )

    pd.DataFrame(period_2022).to_csv(
        "data/backtest_results_soxl_reserved_2022.csv", index=False, encoding="utf-8-sig"
    )
    print("[INFO] 2022년 구간 비교 결과 저장 완료: data/backtest_results_soxl_reserved_2022.csv")

    if period_stats:
        period_path = "data/backtest_results_soxl_reserved_period.csv"
        pd.DataFrame([{"시작일": PERIOD_START, **period_stats}]).to_csv(
            period_path, index=False, encoding="utf-8-sig"
        )
        print(f"[INFO] {PERIOD_START} 이후 구간 재계산 결과 저장 완료: {period_path}")


if __name__ == "__main__":
    main()
