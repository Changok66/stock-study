"""
SOXL 전용 "비중 조절" 백테스트.

backtest_multi.py의 SOXL 그룹(run_cloud_strategy)은 "완전 진입/완전 청산"
방식이다: 피보 골든크로스(+양운 필터)에서 100% 매수, 피보 데드크로스에서 100% 매도.

이 스크립트는 매매 트리거(피보 GC/DC)는 그대로 두되, 데드크로스가 떠도 완전
청산하지 않고 목표 비중(예: 30%/50%)까지만 줄이고, 그 상태에서 다음 골든크로스
(+양운 필터)가 뜨면 다시 100%로 채우는 "부분 비중" 방식을 시뮬레이션한다.

음운 구간에도 목표 비중만큼 계속 시세에 노출되므로, backtest.py/backtest_multi.py처럼
매매 시점 가격만으로 거래 단위 복리를 계산하는 방식이 아니라, 하루 단위로 비중x가격
변동을 반영하는 자산곡선(equity curve)을 시뮬레이션해야 한다. 목표비중=0%로 두면
이 자산곡선이 정확히 "완전 진입/청산" 방식(backtest_multi.py의 SOXL 결과)과 같은
값으로 수렴한다(신호일 다음날 시가 체결, 보유 중 종가~종가 복리 telescoping이 동일).

일별 자산곡선 모델:
- 전날 종가 -> 오늘 시가(오버나이트 구간): 전날 마감 비중(current_target)이 적용된다.
- 오늘 시가에 리밸런싱(비중 변경)이 예정돼 있으면 그 시가에 체결하고, 거래된 비중만큼
  수수료(매수 BUY_FEE_RATE / 매도 SELL_FEE_RATE)를 뗀다.
- 오늘 시가 -> 오늘 종가(장중 구간): 리밸런싱 이후 비중(new_weight)이 적용된다.
- 리밸런싱 여부는 전날 신호(피보 GC/DC + 양운 필터)로 "오늘 시가에 체결"하도록 예약해둔 것을
  그대로 실행한다(신호 다음날 시가 체결 - 기존 프로젝트 규칙과 동일).
"""

import pandas as pd

import backtest as bt
import backtest_multi as bm
import metrics

SOXL_PRICE_PATH = "data/price_SOXL.csv"
RESULTS_PATH = "data/backtest_results_soxl_partial.csv"

# 시나리오: 음운(선1<선2)일 때 유지할 목표 비중(%). 0%가 기존 완전청산 방식과 동일.
SCENARIOS = [
    {"이름": "완전청산(기존)", "음운비중(%)": 0},
    {"이름": "음운 30% 유지", "음운비중(%)": 30},
    {"이름": "음운 50% 유지", "음운비중(%)": 50},
]


def simulate_partial_weight(df: pd.DataFrame, crossovers: pd.DataFrame, bear_weight: float) -> pd.DataFrame:
    """
    df: prepare_stock_data()가 반환하는, Date/Open/Close/선1/선2가 계산된 전체 데이터프레임
        (시간순 정렬돼 있어야 한다).
    crossovers: 피보 골든/데드크로스 지점 (fi.detect_cloud_crossovers 결과).
    bear_weight: 음운일 때 유지할 목표 비중(0.0~1.0). 0.0이면 기존 완전청산과 동일.

    반환값: Date를 인덱스로 하는 DataFrame. 컬럼:
    - 비중: 그날 장중(시가~종가) 적용된 비중
    - 자산배수: 시작을 1.0으로 한 누적 자산 배수(그날 종가 기준)
    """
    df = df.sort_values("Date").reset_index(drop=True)
    golden_dates = set(crossovers.loc[crossovers["종류"] == "골든크로스", "Date"])
    dead_dates = set(crossovers.loc[crossovers["종류"] == "데드크로스", "Date"])

    n = len(df)
    dates = df["Date"].tolist()
    opens = df["Open"].tolist()
    closes = df["Close"].tolist()

    current_target = 0.0     # 현재(전날 마감 시점) 비중
    pending_target = None    # 전날 신호로 "오늘 시가에" 실행하기로 예약된 목표 비중

    weight_today = [0.0] * n   # 그날 장중(시가~종가)에 적용된 비중
    equity = [1.0] * n

    for t in range(n):
        weight_overnight = current_target  # 전날 종가 -> 오늘 시가 구간에 적용되는 비중

        if pending_target is not None and pending_target != current_target:
            new_weight = pending_target
        else:
            new_weight = current_target

        delta = new_weight - current_target
        current_target = new_weight
        weight_today[t] = new_weight

        if t == 0:
            equity[t] = 1.0
        else:
            overnight_factor = 1 + weight_overnight * (opens[t] / closes[t - 1] - 1)
            if delta > 0:
                fee_factor = 1 - delta * bt.BUY_FEE_RATE
            elif delta < 0:
                fee_factor = 1 - abs(delta) * bt.SELL_FEE_RATE
            else:
                fee_factor = 1.0
            intraday_factor = 1 + new_weight * (closes[t] / opens[t] - 1)
            equity[t] = equity[t - 1] * overnight_factor * fee_factor * intraday_factor

        # 오늘(t)의 신호를 보고, 다음날(t+1) 시가에 실행할 목표 비중을 예약한다
        pending_target = None
        date = dates[t]
        row = df.iloc[t]
        if date in golden_dates:
            is_bull_cloud = pd.notna(row["선1"]) and pd.notna(row["선2"]) and row["선1"] > row["선2"]
            if is_bull_cloud and current_target < 1.0:
                pending_target = 1.0
        elif date in dead_dates:
            if current_target > bear_weight:
                pending_target = bear_weight

    result = pd.DataFrame({"Date": dates, "비중": weight_today, "자산배수": equity})
    return result.set_index("Date")


def compute_cagr(equity: pd.Series) -> float:
    """자산배수 시계열 전체 기간을 연복리수익률(CAGR, %)로 환산한다."""
    days = (equity.index[-1] - equity.index[0]).days
    years = days / 365.25
    if years <= 0 or equity.iloc[-1] <= 0:
        return 0.0
    return ((equity.iloc[-1] ** (1 / years)) - 1) * 100


def compute_mdd(equity: pd.Series) -> float:
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    return drawdown.min() * 100


def compute_buy_and_hold_equity(df: pd.DataFrame) -> pd.Series:
    """비교 기준: 첫날 시가 매수(매수수수료) 후 계속 보유, 그날 종가로 평가한 자산배수."""
    df = df.sort_values("Date").reset_index(drop=True)
    buy_cost = df.iloc[0]["Open"] * (1 + bt.BUY_FEE_RATE)
    equity = df["Close"] / buy_cost
    equity.index = pd.DatetimeIndex(df["Date"])
    return equity


def main():
    df, crossovers = bm.prepare_stock_data(SOXL_PRICE_PATH)
    print(f"[INFO] SOXL 데이터 구간: {df['Date'].min().date()} ~ {df['Date'].max().date()} ({len(df)}거래일)")

    bh_equity = compute_buy_and_hold_equity(df)
    bh_total_return = (bh_equity.iloc[-1] - 1) * 100
    bh_mdd = compute_mdd(bh_equity)
    bh_cagr = compute_cagr(bh_equity)
    bh_calmar = bh_cagr / abs(bh_mdd) if bh_mdd != 0 else float("inf")
    print(f"[INFO] Buy&Hold 총수익률: {bh_total_return:.2f}%  MDD: {bh_mdd:.2f}%  CAGR: {bh_cagr:.2f}%  Calmar: {bh_calmar:.2f}")

    rows = []
    for scenario in SCENARIOS:
        bear_weight = scenario["음운비중(%)"] / 100
        sim = simulate_partial_weight(df, crossovers, bear_weight)
        equity = sim["자산배수"]

        total_return = (equity.iloc[-1] - 1) * 100
        mdd = compute_mdd(equity)
        cagr = compute_cagr(equity)
        calmar = cagr / abs(mdd) if mdd != 0 else float("inf")
        capture_pct = total_return / bh_total_return * 100 if bh_total_return != 0 else 0.0

        rows.append({
            "시나리오": scenario["이름"],
            "음운비중(%)": scenario["음운비중(%)"],
            "총수익률(%)": round(total_return, 2),
            "MDD(%)": round(mdd, 2),
            "CAGR(%)": round(cagr, 2),
            "BuyHold대비포착률(%)": round(capture_pct, 2),
            "Calmar(CAGR/|MDD|)": round(calmar, 2),
        })

    rows.append({
        "시나리오": "Buy&Hold(참고)",
        "음운비중(%)": 100,
        "총수익률(%)": round(bh_total_return, 2),
        "MDD(%)": round(bh_mdd, 2),
        "CAGR(%)": round(bh_cagr, 2),
        "BuyHold대비포착률(%)": 100.0,
        "Calmar(CAGR/|MDD|)": round(bh_calmar, 2),
    })

    results_df = pd.DataFrame(rows)
    print("\n[SOXL 비중 조절 시나리오 비교]")
    print(results_df.to_string(index=False))

    results_df.to_csv(RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n[INFO] 결과 저장 완료: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
