"""
backtest.py가 만든 매매 내역(data/backtest_trades.csv)을 읽어
전략의 성과를 요약하는 지표들(승률, 손익비, 최대낙폭, 샤프비율)을 계산한다.
"""

import pandas as pd

TRADES_CSV_PATH = "data/backtest_trades.csv"


def load_trades(path: str = TRADES_CSV_PATH) -> pd.DataFrame:
    """매매 내역 CSV를 읽어 DataFrame으로 반환한다."""
    return pd.read_csv(path, encoding="utf-8-sig")


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


def calc_mdd(trades: pd.DataFrame) -> float:
    """
    최대낙폭(MDD, Maximum Drawdown, %): 매매를 순서대로 복리 누적했을 때의
    자산 곡선이, 그 시점까지의 고점(peak) 대비 가장 많이 떨어졌던 비율.

    이 숫자가 뜻하는 것: 이 전략을 그대로 따라했을 때 과거 기준으로 자산이
    최고점 대비 최대 몇 %까지 줄어든 적이 있었는지를 나타낸다. 절댓값이 클수록
    변동성과 리스크가 크고, 실제로 버티기 심리적으로 힘든 전략이라는 뜻이다.
    """
    if trades.empty:
        return 0.0

    cumulative = (1 + trades["수익률(%)"] / 100).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
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
    print(f"[INFO] 매매 건수: {len(trades)}건")
    print(f"승률: {calc_win_rate(trades):.2f}%")
    print(f"손익비: {calc_profit_loss_ratio(trades):.2f}")
    print(f"최대낙폭(MDD): {calc_mdd(trades):.2f}%")
    print(f"샤프비율: {calc_sharpe_ratio(trades):.2f}")


if __name__ == "__main__":
    main()
