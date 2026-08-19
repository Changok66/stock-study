"""
get_data.py에 등록된 종목 그룹(--group)에 대해 "양운(선1>선2)일 때 피보
골든크로스 매수 / 피보 데드크로스 매도" 전략을 종목별로 백테스트하고,
종목별 성과 + 전체 종목 합산 성과 + 종목별 매매내역을 CSV로 저장하는 스크립트.

종목 그룹(--group, 기본값 stocks):
- stocks: get_data.STOCKS (삼성전자 + 시가총액 상위/업종 다양화 7종목)
  -> data/backtest_results_multi.csv, data/backtest_trades_multi.csv
- holdings: get_data.HOLDINGS (실제 보유종목 9종목)
  -> data/backtest_results_holdings.csv, data/backtest_trades_holdings.csv

전략:
- 매수 신호: fibo_indicator.py가 이미 계산하는 피보 골든크로스(피보 구름 중심이
  역피보 구름 중심을 아래에서 위로 돌파)가 뜬 날, 그날 종가 기준 선1 > 선2
  (양운)이면 다음 거래일 시가에 매수한다. 양운이 아니면 골든크로스가 떠도
  매수하지 않는다(backtest.py가 ADX>25를 매수 필터로 쓰는 것과 같은 자리에
  양운 여부를 넣은 구조).
- 매도 신호: 피보 데드크로스가 뜨면(양운/음운과 무관하게 무조건) 다음 거래일
  시가에 매도한다.
- 종목당 동시에 1포지션만 보유한다: 이미 보유 중이면 골든크로스를 무시하고,
  미보유 중이면 데드크로스를 무시한다(backtest.py의 run_backtest()와 동일 규칙).
- 매매 수수료/거래세율, 누적 수익률 복리 계산은 backtest.py의 것을 그대로
  재사용한다(BUY_FEE_RATE/SELL_FEE_RATE/compute_cumulative_return).
- 승률/손익비/MDD는 metrics.py의 계산 함수를 그대로 재사용한다(둘 다
  "수익률(%)" 컬럼을 가진 매매 내역 DataFrame에 대해 동작하도록 이미 작성돼 있어
  종목이 몇 개든, 종목별이든 전체 합산이든 같은 함수로 계산할 수 있다).

전체 종목 합산 통계:
- 매매건수/승률/손익비는 각 종목의 완료된 매매를 전부 모은 통합 매매 내역에 대해
  계산한다(매매 하나하나를 동등하게 취급 - 겹치는 보유기간이 있어도 결과가 왜곡되지 않는다).
- 총수익률/MDD는 통합 매매 내역을 그대로 복리로 곱하면 안 된다: 이 종목군은 서로
  다른 종목이 같은 기간에 동시에 포지션을 들고 있는 경우가 많아서(예: holdings
  9종목은 102건 중 129쌍이 보유기간이 겹친다), "모든 거래를 매도일 순서로 그냥
  복리로 이어붙이는" 방식은 자본 100%가 매 신호마다 다음 거래로 즉시 옮겨간다고
  가정하는 셈이 되어 겹치는 기간만큼 수익률이 기하급수적으로 부풀려진다.
  대신 종목마다 자본을 균등 비중(1/N)으로 나눠 투자했다고 가정한 포트폴리오
  누적자산 곡선(build_equity_series/combine_equal_weight_portfolio)을 만들어
  그 곡선의 최종 수익률과 최대낙폭을 쓴다.
"""

import argparse

import pandas as pd

import backtest as bt
import fibo_indicator as fi
import ichimoku_custom_indicator as ichi
import metrics
from get_data import HOLDINGS, STOCKS

GROUPS = {
    "stocks": {
        "registry": STOCKS,
        "results_path": "data/backtest_results_multi.csv",
        "trades_path": "data/backtest_trades_multi.csv",
    },
    "holdings": {
        "registry": HOLDINGS,
        "results_path": "data/backtest_results_holdings.csv",
        "trades_path": "data/backtest_trades_holdings.csv",
    },
}


def prepare_stock_data(csv_path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    종목 하나의 CSV를 읽어 피보/역피보/구름 교차 지점과 선1/선2(양운/음운)를
    계산한 DataFrame, 교차 지점 DataFrame을 돌려준다.
    fibo_indicator.py/ichimoku_custom_indicator.py의 계산 함수를 그대로 재사용한다.
    """
    df = fi.load_data(csv_path)
    df = fi.add_ma(df)
    df = fi.add_fibo(df)
    df = fi.add_bollinger_bands(df)
    df = fi.add_inverse_fibo(df)

    crossovers = fi.detect_cloud_crossovers(df)
    crossovers = crossovers.sort_values("Date").reset_index(drop=True)

    df = ichi.add_senkou_spans(df)

    return df, crossovers


def run_cloud_strategy(df: pd.DataFrame, crossovers: pd.DataFrame) -> tuple[pd.DataFrame, dict | None]:
    """
    backtest.py의 run_backtest()와 같은 구조(다음 거래일 시가 체결, 종목당 1포지션)이되,
    매수 필터가 "ADX > 25" 대신 "양운(선1 > 선2)"이다. 매도는 데드크로스가 뜨면
    양운/음운과 무관하게 실행한다.

    반환값: (완료된 매매 내역 DataFrame, 미청산 포지션 정보 dict 또는 None)
    """
    df = df.sort_values("Date").reset_index(drop=True)
    golden_dates = set(crossovers.loc[crossovers["종류"] == "골든크로스", "Date"])
    dead_dates = set(crossovers.loc[crossovers["종류"] == "데드크로스", "Date"])

    trades = []
    position = None  # {"buy_date":..., "buy_price":...} 형태로 보유 중인 매수 정보 저장

    # 마지막 행은 "다음 거래일"이 없어 그날 신호가 떠도 실행할 수 없으므로 반복에서 제외
    for i in range(len(df) - 1):
        row = df.iloc[i]
        next_day = df.iloc[i + 1]
        date = row["Date"]

        if position is None:
            if date in golden_dates:
                is_bull_cloud = pd.notna(row["선1"]) and pd.notna(row["선2"]) and row["선1"] > row["선2"]
                if is_bull_cloud:
                    position = {"buy_date": next_day["Date"], "buy_price": next_day["Open"]}

        else:
            if date in dead_dates:
                sell_date = next_day["Date"]
                sell_price = next_day["Open"]
                buy_date = position["buy_date"]
                buy_price = position["buy_price"]

                buy_cost = buy_price * (1 + bt.BUY_FEE_RATE)
                sell_proceeds = sell_price * (1 - bt.SELL_FEE_RATE)
                return_rate = sell_proceeds / buy_cost - 1

                trades.append({
                    "매수일": buy_date,
                    "매도일": sell_date,
                    "매수가": buy_price,
                    "매도가": sell_price,
                    "수익률(%)": round(return_rate * 100, 2),
                })
                position = None

    trades_df = pd.DataFrame(trades)
    return trades_df, position


def summarize(trades_df: pd.DataFrame) -> dict:
    """
    종목 하나의 매매 내역을 승률/손익비/총수익률/MDD로 요약한다.
    metrics.py/backtest.py의 계산 함수를 그대로 재사용한다.
    (단일 종목은 매매가 겹칠 일이 없으므로 복리 누적 방식 그대로 써도 된다 -
    여러 종목을 합산할 때의 문제는 build_equity_series/combine_equal_weight_portfolio 참고)
    """
    if trades_df.empty:
        return {"매매건수": 0, "승률(%)": 0.0, "손익비": 0.0, "총수익률(%)": 0.0, "MDD(%)": 0.0}

    return {
        "매매건수": len(trades_df),
        "승률(%)": round(metrics.calc_win_rate(trades_df), 2),
        "손익비": round(metrics.calc_profit_loss_ratio(trades_df), 2),
        "총수익률(%)": round(bt.compute_cumulative_return(trades_df), 2),
        "MDD(%)": round(metrics.calc_mdd(trades_df), 2),
    }


def build_equity_series(trades_df: pd.DataFrame) -> pd.Series:
    """
    종목 하나의 매매 내역을, 매도일에 수익률만큼 계단식으로 뛰는 누적자산(시작=1.0)
    시계열로 바꾼다. 매매가 없는 기간에는 직전 값을 그대로 유지한다고 본다
    (포지션이 없을 때는 현금을 들고 있는 것과 같아서 자산 가치가 변하지 않는다).
    """
    if trades_df.empty:
        return pd.Series(dtype=float)

    trades_df = trades_df.sort_values("매도일")
    equity = (1 + trades_df["수익률(%)"] / 100).cumprod()
    equity.index = pd.DatetimeIndex(trades_df["매도일"])
    return equity


def combine_equal_weight_portfolio(equity_series_list: list[pd.Series]) -> pd.Series:
    """
    종목별 누적자산(시작=1.0) 시계열을 자본 균등 비중(1/N)으로 나눠 투자했다고
    가정하고 합산한 "포트폴리오 누적자산(배)" 시계열을 만든다.

    각 시계열의 날짜를 모두 합친 공통 타임라인 위에서, 종목마다 자기 시계열을
    직전 값으로 채워 넣은(ffill) 뒤 1/N씩 가중해 더한다 - 그래야 여러 종목이
    동시에 포지션을 들고 있어도(보유기간이 겹쳐도) 자본이 이중으로 잡히지 않는다.
    시계열이 시작되기 전(그 종목의 첫 매도일 이전) 구간은 아직 투자되지 않은
    자본이므로 1.0(원금 그대로)으로 채운다.
    """
    non_empty = [s for s in equity_series_list if not s.empty]
    if not non_empty:
        return pd.Series(dtype=float)

    all_dates = sorted(set().union(*(s.index for s in non_empty)))
    n = len(equity_series_list)

    portfolio = pd.Series(0.0, index=all_dates)
    for s in non_empty:
        filled = s.reindex(all_dates).ffill().fillna(1.0)
        portfolio = portfolio.add(filled / n)

    # 매매가 하나도 없던 종목은 끝까지 1.0(원금 그대로)만큼 비중을 차지한다
    empty_count = len(equity_series_list) - len(non_empty)
    portfolio = portfolio + empty_count / n

    return portfolio


def compute_portfolio_return_mdd(equity_series_list: list[pd.Series]) -> tuple[float, float]:
    """균등비중 포트폴리오 누적자산 곡선의 최종 총수익률(%)과 최대낙폭(MDD, %)을 계산한다."""
    portfolio = combine_equal_weight_portfolio(equity_series_list)
    if portfolio.empty:
        return 0.0, 0.0

    total_return = (portfolio.iloc[-1] - 1) * 100
    running_max = portfolio.cummax()
    drawdown = (portfolio - running_max) / running_max
    mdd = drawdown.min() * 100
    return total_return, mdd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="양운+피보크로스 전략 다종목 백테스트")
    parser.add_argument(
        "--group", choices=list(GROUPS.keys()), default="stocks",
        help="stocks=시가총액상위/업종다양화 8종목(기본값), holdings=실제 보유종목 9종목",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    group = GROUPS[args.group]
    registry = group["registry"]

    results = []
    all_trades = []
    equity_series_list = []

    for code, info in registry.items():
        name = info["name"]
        path = info["output"]
        print(f"[INFO] {name}({code}) 백테스트 중...")

        df, crossovers = prepare_stock_data(path)
        trades_df, open_position = run_cloud_strategy(df, crossovers)

        summary = {"종목코드": code, "종목명": name, **summarize(trades_df)}
        results.append(summary)
        equity_series_list.append(build_equity_series(trades_df))

        if not trades_df.empty:
            tagged = trades_df.copy()
            tagged["종목코드"] = code
            tagged["종목명"] = name
            all_trades.append(tagged)

        if open_position is not None:
            print(
                f"  [참고] 미청산 포지션: 매수일 {open_position['buy_date'].date()}, "
                f"매수가 {open_position['buy_price']:,.0f}원"
            )

    results_df = pd.DataFrame(results)

    # 전체 종목 합산: 매매건수/승률/손익비는 모든 종목의 완료된 매매를 하나로 모아 계산하고
    # (매매 하나하나를 동등하게 취급하는 통계라 겹치는 보유기간이 있어도 문제없다),
    # 총수익률/MDD는 균등비중(1/N) 포트폴리오 누적자산 곡선 기준으로 따로 계산한다
    # (겹치는 보유기간을 그대로 복리로 곱하면 수익률이 부풀려지므로 - 모듈 docstring 참고)
    trades_cols = ["종목코드", "종목명", "매수일", "매도일", "매수가", "매도가", "수익률(%)"]
    if all_trades:
        combined = pd.concat(all_trades, ignore_index=True).sort_values("매도일").reset_index(drop=True)
    else:
        combined = pd.DataFrame(columns=trades_cols)

    combined_stats = summarize(combined)
    portfolio_return, portfolio_mdd = compute_portfolio_return_mdd(equity_series_list)
    combined_stats["총수익률(%)"] = round(portfolio_return, 2)
    combined_stats["MDD(%)"] = round(portfolio_mdd, 2)
    combined_summary = {"종목코드": "전체", "종목명": "전체 합산(균등비중)", **combined_stats}

    results_df = pd.concat([results_df, pd.DataFrame([combined_summary])], ignore_index=True)

    print("\n[종목별 + 전체 합산 백테스트 결과]")
    print(results_df.to_string(index=False))

    results_df.to_csv(group["results_path"], index=False, encoding="utf-8-sig")
    print(f"\n[INFO] 결과 저장 완료: {group['results_path']}")

    # 종목별 매매내역(매도일 순 통합)도 함께 저장한다
    if not combined.empty:
        combined[trades_cols].to_csv(group["trades_path"], index=False, encoding="utf-8-sig")
        print(f"[INFO] 매매내역 저장 완료: {group['trades_path']} ({len(combined)}건)")
    else:
        print("[INFO] 완료된 매매가 없어 매매내역 CSV는 저장하지 않았습니다.")


if __name__ == "__main__":
    main()
