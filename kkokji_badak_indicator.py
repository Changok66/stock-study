"""
2026-08-20 세션에서 새로 나온 "꼭지4/바닥4" 지표를 계산하는 모듈.
추세필터(MA17 5일 기울기) + 롤링 매매 전략(backtest_soxl_trend_rolling.py)의
매수(바닥4)/매도(꼭지4) 신호로 쓰인다.

공식 (shortPeriod=4, midPeriod=8, longPeriod=16, D1=4):
- X = (highest(High,sp) + lowest(Low,sp) + highest(High,mp) + lowest(Low,mp)) / 4
- 꼭지4 = (X + BBandsUp(Close,mp,D1)) / 2
- 바닥4 = (X + BBandsDown(Close,mp,D1)) / 2
- BBandsUp/Down = MA(Close,period) ± D1 × STD(Close,period)
  (STD는 ddof=0 모집단 표준편차 - up_down_43_indicator.py의 _bbands()와 동일한 관례)

longPeriod(lp)는 파라미터로 받지만, 위 공식 자체에는 등장하지 않는다(사용자가 전달한
원본 공식 그대로 구현 - lp는 현재 계산에 관여하지 않는다). 나중에 꼭지5/바닥5 같은
5번대 밴드가 추가되면 그때 쓰일 자리로 남겨둔다.
"""

import pandas as pd


def add_kkokji_badak(
    df: pd.DataFrame,
    short_period: int = 4,
    mid_period: int = 8,
    long_period: int = 16,
    d1: float = 4,
) -> pd.DataFrame:
    """꼭지4/바닥4를 계산해 컬럼으로 추가한다."""
    high, low, close = df["High"], df["Low"], df["Close"]

    hh_sp = high.rolling(window=short_period).max()
    ll_sp = low.rolling(window=short_period).min()
    hh_mp = high.rolling(window=mid_period).max()
    ll_mp = low.rolling(window=mid_period).min()
    x = (hh_sp + ll_sp + hh_mp + ll_mp) / 4

    ma_mp = close.rolling(window=mid_period).mean()
    std_mp = close.rolling(window=mid_period).std(ddof=0)
    bb_up = ma_mp + d1 * std_mp
    bb_down = ma_mp - d1 * std_mp

    df["꼭지4"] = (x + bb_up) / 2
    df["바닥4"] = (x + bb_down) / 2

    _ = long_period  # 현재 공식에는 쓰이지 않음 (위 docstring 참고)
    return df
