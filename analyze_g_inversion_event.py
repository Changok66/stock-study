"""
G라인(43/-43 일목, 15일 선행shift)이 Up구름(Up4~Up5) 위로 역전되는 시점을 이벤트로 잡아,
그 이후 며칠간 실제 가격이 어떻게 움직였는지(수익률/변동성) 살펴보는 이벤트 스터디.

가설: G라인 역전 = 변동성 급등 = 기존 눌림목매수(Up구름 반등/G라인 회복) 로직이 위험한 구간
이라는 신호. 이 스크립트는 그 가설을 SOXL과 삼성전자 데이터로 검증한다(전략 백테스트가
아니라, "이 신호가 뜬 뒤 실제로 무슨 일이 일어났는지"를 보는 사건연구).

역전 이벤트 정의: G > Up구름 상단(max(Up4,Up5))인 상태로 "처음" 진입하는 날
(전날은 G<=Up구름 상단, 오늘은 G>Up구름 상단).
"""

import pandas as pd

import up_down_43_indicator as ud43

HORIZONS = [1, 3, 5, 10, 20]  # 이벤트 이후 며칠(거래일)을 볼지


def prepare(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    df = ud43.add_up_down_cloud(df, p1=25, p2=50, d1=2)
    df = ud43.add_43_indicator(df, p1=50, p2=25, shift_days=15)
    return df


def find_inversion_events(df: pd.DataFrame) -> pd.DataFrame:
    """G > Up구름 상단으로 처음 진입하는 날짜 목록을 반환한다."""
    up_upper = df[["Up4", "Up5"]].max(axis=1)
    state_up = (df["G"] > up_upper) & df["G"].notna() & up_upper.notna()
    entered = state_up & ~state_up.shift(1, fill_value=False)
    return df.loc[entered, ["Date"]].reset_index(drop=True)


def event_study(df: pd.DataFrame, events: pd.DataFrame, label: str) -> pd.DataFrame:
    df = df.reset_index(drop=True)
    date_to_idx = {d: i for i, d in enumerate(df["Date"])}
    close = df["Close"]

    # 베이스라인(무조건부): 전체 구간의 N일 수익률/변동성 평균 - 이벤트 이후와 비교하기 위한 기준선
    daily_ret = close.pct_change()
    baseline_vol = daily_ret.std() * 100

    rows = []
    for _, row in events.iterrows():
        idx = date_to_idx.get(row["Date"])
        if idx is None:
            continue
        rec = {"이벤트일": row["Date"].date()}
        for h in HORIZONS:
            if idx + h < len(df):
                fwd_ret = (close.iloc[idx + h] / close.iloc[idx] - 1) * 100
                fwd_vol = daily_ret.iloc[idx + 1: idx + h + 1].std() * 100 if h > 1 else None
                rec[f"{h}일수익률(%)"] = round(fwd_ret, 2)
                if fwd_vol is not None:
                    rec[f"{h}일변동성(%)"] = round(fwd_vol, 2)
        rows.append(rec)

    result = pd.DataFrame(rows)
    print(f"\n[{label}] G라인 Up구름 역전 이벤트: {len(events)}건 (전체구간 일일변동성 기준선: {baseline_vol:.2f}%)")
    if not result.empty:
        print(result.to_string(index=False))
        print(f"\n[{label}] 이벤트 이후 평균:")
        for h in HORIZONS:
            ret_col = f"{h}일수익률(%)"
            vol_col = f"{h}일변동성(%)"
            if ret_col in result.columns:
                avg_ret = result[ret_col].mean()
                line = f"  {h}일 평균수익률: {avg_ret:+.2f}%"
                if vol_col in result.columns:
                    avg_vol = result[vol_col].mean()
                    line += f"  |  {h}일 평균변동성: {avg_vol:.2f}% (기준선 {baseline_vol:.2f}% 대비 {avg_vol - baseline_vol:+.2f}%p)"
                print(line)
    return result


def main():
    soxl_df = prepare("data/price_SOXL.csv")
    soxl_events = find_inversion_events(soxl_df)
    soxl_result = event_study(soxl_df, soxl_events, "SOXL")
    if not soxl_result.empty:
        soxl_result.to_csv("data/g_inversion_events_soxl.csv", index=False, encoding="utf-8-sig")

    samsung_df = prepare("data/samsung.csv")
    samsung_events = find_inversion_events(samsung_df)
    samsung_result = event_study(samsung_df, samsung_events, "삼성전자")
    if not samsung_result.empty:
        samsung_result.to_csv("data/g_inversion_events_samsung.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
