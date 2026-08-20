"""
backtest.py가 만든 매매 내역(data/backtest_trades.csv)을 읽어
전략의 성과를 요약하는 지표들(승률, 손익비, 최대낙폭, 샤프비율)을 계산한다.
"""

import pandas as pd

import backtest as bt
import fibo_indicator as fi

TRADES_CSV_PATH = "data/backtest_trades.csv"


def load_trades(path: str = TRADES_CSV_PATH) -> pd.DataFrame:
    """매매 내역 CSV를 읽어 DataFrame으로 반환한다."""
    return pd.read_csv(path, encoding="utf-8-sig")


def build_daily_equity(trades_df: pd.DataFrame, price_df: pd.DataFrame) -> pd.Series:
    """
    매매 내역(매수일/매도일)과 종목의 일별 시가/종가(price_df, Date/Open/Close 컬럼)를 이용해,
    실제 보유 중 일별 가격 변동을 그대로 반영한 mark-to-market 누적자산(시작=1.0) 시계열을 만든다.

    - 매수일: 그날 시가에 매수(매수 수수료 반영). 전날 종가~그날 시가(오버나이트) 구간은
      아직 매수 전이므로 미보유, 그날 시가~종가(장중) 구간부터 보유가 반영된다.
    - 매도일: 그날 시가에 매도(매도 수수료+거래세 반영). 전날 종가~그날 시가(오버나이트)
      구간까지는 보유 중이었으므로 반영되고, 시가~종가(장중) 구간은 매도 후라 미보유.
    - 매수일과 매도일 사이의 날: 하루 종일(전날 종가~그날 종가) 보유가 반영된다.
    - 포지션이 없는 날은 직전 값을 그대로 유지한다(현금 보유와 동일 - 가격 변동 없음).

    단일 종목(포지션이 겹치지 않음)을 전제로 한다. 여러 종목을 합친 매매 내역을 넣으면
    안 된다 - 그 경우는 backtest_multi.py의 build_equity_series/combine_equal_weight_portfolio
    (종목별 자산곡선을 균등비중으로 합산)를 대신 써야 한다.
    """
    if trades_df.empty:
        return pd.Series(dtype=float)

    price_df = price_df.sort_values("Date").reset_index(drop=True)
    dates = price_df["Date"]
    opens = price_df["Open"].to_numpy()
    closes = price_df["Close"].to_numpy()
    n = len(price_df)

    buy_dates = set(pd.to_datetime(trades_df["매수일"]))
    sell_dates = set(pd.to_datetime(trades_df["매도일"]))

    current_weight = 0.0
    equity = [1.0] * n
    for t in range(n):
        date = dates.iloc[t]
        weight_overnight = current_weight

        if date in buy_dates:
            new_weight = 1.0
        elif date in sell_dates:
            new_weight = 0.0
        else:
            new_weight = current_weight

        delta = new_weight - current_weight
        current_weight = new_weight

        if t == 0:
            continue

        overnight_factor = 1 + weight_overnight * (opens[t] / closes[t - 1] - 1)
        if delta > 0:
            fee_factor = 1 - delta * bt.BUY_FEE_RATE
        elif delta < 0:
            fee_factor = 1 - abs(delta) * bt.SELL_FEE_RATE
        else:
            fee_factor = 1.0
        intraday_factor = 1 + new_weight * (closes[t] / opens[t] - 1)
        equity[t] = equity[t - 1] * overnight_factor * fee_factor * intraday_factor

    return pd.Series(equity, index=pd.DatetimeIndex(dates))


def calc_win_rate(trades: pd.DataFrame) -> float:
    """
    승률(%): 전체 매매 중 수익(수익률 > 0)으로 끝난 매매의 비율.

    이 숫자가 뜻하는 것: 이 전략으로 100번 매매하면 그중 몇 번을 벌었는지를 나타낸다.
    승률이 높다고 반드시 전체 성과가 좋은 것은 아니다 - 승률이 낮아도 한 번 벌 때 크게
    벌고 잃을 때는 조금만 잃는 전략(손익비가 큰 전략)이면 전체적으로는 수익일 수 있으므로,
    반드시 calc_profit_loss_ratio와 함께 봐야 한다.
    """
    if trades.empty:
        return 0.0

    wins = (trades["수익률(%)"] > 0).sum()
    return wins / len(trades) * 100


def calc_profit_loss_ratio(trades: pd.DataFrame) -> float:
    """
    손익비: 이긴 매매들의 평균 수익률 / 진 매매들의 평균 손실률(절댓값).

    이 숫자가 뜻하는 것: 한 번 벌 때 평균적으로 얻는 수익이, 한 번 잃을 때 평균적으로
    보는 손실의 몇 배인지를 나타낸다. 예를 들어 손익비가 2.0이면 "평균적으로 벌 때는
    잃을 때의 2배를 번다"는 뜻. 손익비가 크면 승률이 낮아도 장기적으로 수익을 낼 수 있다.
    손실 매매가 하나도 없으면 나눌 손실이 없으므로 무한대(inf)를 반환한다.
    """
    wins = trades.loc[trades["수익률(%)"] > 0, "수익률(%)"]
    losses = trades.loc[trades["수익률(%)"] < 0, "수익률(%)"]

    if losses.empty:
        return float("inf")
    if wins.empty:
        return 0.0

    return wins.mean() / abs(losses.mean())


def calc_mdd(trades: pd.DataFrame, price_df: pd.DataFrame) -> float:
    """
    최대낙폭(MDD, Maximum Drawdown, %): 매매 내역을 일별 시가/종가에 그대로
    mark-to-market한 자산곡선(build_daily_equity)이, 그 시점까지의 고점(peak)
    대비 가장 많이 떨어졌던 비율.

    이 숫자가 뜻하는 것: 이 전략을 그대로 따라했을 때 과거 기준으로 자산이
    최고점 대비 최대 몇 %까지 줄어든 적이 있었는지를 나타낸다. 절댓값이 클수록
    변동성과 리스크가 크고, 실제로 버티기 심리적으로 힘든 전략이라는 뜻이다.

    예전에는 완료된 거래의 결과값만 순서대로 복리 계산해서 MDD를 구했는데, 그
    방식은 보유 도중(매수일~매도일 사이)의 일별 고점/저점을 놓친다 - 어떤 거래가
    최종적으로는 -5% 손실로 끝났어도 보유 중에 장중 고점을 찍고 내려온 것이라면
    실제로는 그 고점 대비 더 크게 떨어진 것인데 예전 방식은 이를 포착하지 못해
    변동성이 큰 종목(SOXL 같은 레버리지 ETF)일수록 MDD를 과소평가했다. 그래서
    일별 mark-to-market 방식으로 교체했다.
    """
    if trades.empty:
        return 0.0

    equity = build_daily_equity(trades, price_df)
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    return drawdown.min() * 100


def calc_sharpe_ratio(trades: pd.DataFrame) -> float:
    """
    샤프비율: 매매별 수익률의 평균을 그 수익률의 표준편차(변동성)로 나눈 값.
    무위험수익률(아무 위험 없이 그냥 얻을 수 있는 수익률, 예: 예금 이자율)은
    0으로 가정하므로 평균 수익률을 그대로 분자로 사용한다.

    이 숫자가 뜻하는 것: 감수한 위험(수익률의 들쭉날쭉한 정도) 한 단위당 얻은
    수익의 크기를 나타낸다. 값이 클수록 적은 위험으로 안정적인 수익을 냈다는 뜻이고,
    0에 가깝거나 음수면 위험 대비 수익이 부실하다(혹은 손해다)는 뜻이다.
    표준편차는 표본표준편차(ddof=1)를 쓰며, 매매가 2건 미만이면 표준편차를
    구할 수 없으므로 0.0을 반환한다.
    """
    returns = trades["수익률(%)"]
    if len(returns) < 2:
        return 0.0

    std = returns.std(ddof=1)
    if std == 0:
        return 0.0

    return returns.mean() / std


def main():
    trades = load_trades()
    price_df = fi.load_data(fi.INPUT_PATH)
    print(f"[INFO] 매매 건수: {len(trades)}건")
    print(f"승률: {calc_win_rate(trades):.2f}%")
    print(f"손익비: {calc_profit_loss_ratio(trades):.2f}")
    print(f"최대낙폭(MDD): {calc_mdd(trades, price_df):.2f}%")
    print(f"샤프비율: {calc_sharpe_ratio(trades):.2f}")


if __name__ == "__main__":
    main()
