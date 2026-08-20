"""
사용자가 실전 매매에서 쓰던 Up/Down 일목 구름과 43/-43 일목(S/G 라인 포함)을 계산하는 모듈.
2026-08-20 세션에서 공식과 파라미터를 확정했다.

Up/Down 일목 (P1=25, P2=50, D1=2):
- Up4 = (lowest(Low,P1) + BBandsDown(Close,P1,D1)) / 2
- Up5 = (lowest(Low,P2) + BBandsDown(Close,P2,D1)) / 2
- Down4 = (highest(High,P1) + BBandsUp(Close,P1,D1)) / 2
- Down5 = (highest(High,P2) + BBandsUp(Close,P2,D1)) / 2
- Up구름 = Up4~Up5 사이 밴드(지지대), Down구름 = Down4~Down5 사이 밴드(저항대)
- BBandsUp/Down = 볼린저밴드 상단/하단 = MA(Close,P) ± D×STD(Close,P)
  (STD는 ddof=0 모집단 표준편차 - fibo_indicator.add_bollinger_bands()와 동일한 관례)

43/-43 일목 (P1=50, P2=25):
- C = (HH(P1)+LL(P1)+MA(P1)+MA(P2)) / 4  (shift 없음)
- 43의4 = (2*HH(P1)+LL(P1)) / 3, 43의5 = (3*HH(P1)+LL(P1)) / 4        (HH(P1) 아래쪽 밴드)
- -43의4 = (HH(P1)+2*LL(P1)) / 3, -43의5 = (HH(P1)+3*LL(P1)) / 4      (LL(P1) 위쪽 밴드)
- S = HH(P1) + (HH(P1)-LL(P1))/4, G = LL(P1) - (HH(P1)-LL(P1))/4
  각각 15일 선행shift(.shift(15)) 적용 - 계산 자체는 당일 데이터(최근 50일 HH/LL)로 하되
  그 값을 15일 뒤 시점에 갖다 쓰는 것이라, 미래 데이터를 끌어쓰는 lookahead bias는 아니다.

C/43의4·5/-43의4·5는 2026-08-20 세션에서 최종 확정된 "43/-43+Up/Down 구름 예약매수" 전략의
매수/매도 신호에는 쓰이지 않는다(실제 신호는 Up/Down구름 + S/G만 사용) - 사용자가 실전에서
함께 보는 지표라 참고용으로 같이 계산해둔다.
"""

import pandas as pd

SHIFT_DAYS = 15


def _bbands(close: pd.Series, period: int, num_std: float) -> tuple[pd.Series, pd.Series]:
    """볼린저밴드 상단/하단을 반환한다. (MA ± num_std × STD, ddof=0)"""
    ma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std(ddof=0)
    upper = ma + num_std * std
    lower = ma - num_std * std
    return upper, lower


def add_up_down_cloud(df: pd.DataFrame, p1: int = 25, p2: int = 50, d1: float = 2) -> pd.DataFrame:
    """Up/Down 일목 구름(Up4/Up5/Down4/Down5)을 계산해 컬럼으로 추가한다."""
    bb_upper_p1, bb_lower_p1 = _bbands(df["Close"], p1, d1)
    bb_upper_p2, bb_lower_p2 = _bbands(df["Close"], p2, d1)

    lowest_p1 = df["Low"].rolling(window=p1).min()
    lowest_p2 = df["Low"].rolling(window=p2).min()
    highest_p1 = df["High"].rolling(window=p1).max()
    highest_p2 = df["High"].rolling(window=p2).max()

    df["Up4"] = (lowest_p1 + bb_lower_p1) / 2
    df["Up5"] = (lowest_p2 + bb_lower_p2) / 2
    df["Down4"] = (highest_p1 + bb_upper_p1) / 2
    df["Down5"] = (highest_p2 + bb_upper_p2) / 2
    return df


def add_43_indicator(df: pd.DataFrame, p1: int = 50, p2: int = 25, shift_days: int = SHIFT_DAYS) -> pd.DataFrame:
    """43/-43 일목(C, 43의4/5, -43의4/5, S/G)을 계산해 컬럼으로 추가한다."""
    hh_p1 = df["High"].rolling(window=p1).max()
    ll_p1 = df["Low"].rolling(window=p1).min()
    ma_p1 = df["Close"].rolling(window=p1).mean()
    ma_p2 = df["Close"].rolling(window=p2).mean()

    df["43_C"] = (hh_p1 + ll_p1 + ma_p1 + ma_p2) / 4
    df["43_4"] = (2 * hh_p1 + ll_p1) / 3
    df["43_5"] = (3 * hh_p1 + ll_p1) / 4
    df["neg43_4"] = (hh_p1 + 2 * ll_p1) / 3
    df["neg43_5"] = (hh_p1 + 3 * ll_p1) / 4

    range_p1 = hh_p1 - ll_p1
    df["S"] = (hh_p1 + range_p1 / 4).shift(shift_days)
    df["G"] = (ll_p1 - range_p1 / 4).shift(shift_days)
    return df
