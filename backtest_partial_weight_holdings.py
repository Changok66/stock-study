"""
backtest_soxl_partial.py에서 만든 "부분 비중 유지" 아이디어(음운 전환 시 완전청산 대신
목표 비중까지만 축소, 양운 재전환 시 다시 100%로 채움)를, HOLDINGS 중 완전청산 방식으로
성과가 부진했던 4종목(대한광통신/두산에너빌리티/아모레퍼시픽/HD현대중공업)에 적용해
"완전청산(기존)" 대비 "음운 30% 유지"가 얼마나 개선되는지 비교한다.

시뮬레이션 로직(일별 mark-to-market 자산곡선)은 backtest_soxl_partial.py의
simulate_partial_weight/compute_cagr/compute_mdd/compute_buy_and_hold_equity를
그대로 재사용한다(SOXL 전용 로직이 아니라 종목에 무관한 일반 로직이기 때문).
"""

import pandas as pd

import backtest_multi as bm
from backtest_soxl_partial import (
    compute_buy_and_hold_equity,
    compute_cagr,
    compute_mdd,
    simulate_partial_weight,
)
from get_data import HOLDINGS

# 완전청산 방식(backtest_results_holdings.csv)에서 성과가 부진했던 4종목
TARGET_CODES = ["010170", "034020", "090430", "329180"]

SCENARIOS = [
    {"이름": "완전청산(기존)", "음운비중(%)": 0},
    {"이름": "음운 30% 유지", "음운비중(%)": 30},
]

RESULTS_PATH = "data/backtest_results_holdings_partial.csv"


def main():
    rows = []
    for code in TARGET_CODES:
        info = HOLDINGS[code]
        name = info["name"]
        path = info["output"]
        print(f"[INFO] {name}({code}) 부분비중 백테스트 중...")

        df, crossovers = bm.prepare_stock_data(path)
        bh_equity = compute_buy_and_hold_equity(df)
        bh_total_return = (bh_equity.iloc[-1] - 1) * 100

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
                "종목코드": code,
                "종목명": name,
                "시나리오": scenario["이름"],
                "음운비중(%)": scenario["음운비중(%)"],
                "총수익률(%)": round(total_return, 2),
                "MDD(%)": round(mdd, 2),
                "CAGR(%)": round(cagr, 2),
                "BuyHold대비포착률(%)": round(capture_pct, 2),
                "Calmar(CAGR/|MDD|)": round(calmar, 2),
            })

    results_df = pd.DataFrame(rows)

    # 종목별로 "완전청산 -> 30% 유지" 개선폭(총수익률/MDD 변화)을 추가로 계산해 보여준다
    print("\n[완전청산 vs 음운 30% 유지 비교]")
    print(results_df.to_string(index=False))

    print("\n[종목별 개선폭 (30% 유지 - 완전청산)]")
    for code in TARGET_CODES:
        sub = results_df[results_df["종목코드"] == code].set_index("시나리오")
        name = sub["종목명"].iloc[0]
        ret_diff = sub.loc["음운 30% 유지", "총수익률(%)"] - sub.loc["완전청산(기존)", "총수익률(%)"]
        mdd_diff = sub.loc["음운 30% 유지", "MDD(%)"] - sub.loc["완전청산(기존)", "MDD(%)"]
        print(f"  {name}({code}): 총수익률 {ret_diff:+.2f}%p, MDD {mdd_diff:+.2f}%p")

    results_df.to_csv(RESULTS_PATH, index=False, encoding="utf-8-sig")
    print(f"\n[INFO] 결과 저장 완료: {RESULTS_PATH}")


if __name__ == "__main__":
    main()
