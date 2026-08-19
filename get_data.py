"""
여러 종목의 최근 5년치 일봉 데이터를 수집하여 CSV로 저장하는 스크립트

데이터 소스는 두 가지를 지원한다 (--source 옵션, 기본값 kiwoom):
- kiwoom: 키움증권 REST API(ka10081, 주식일봉차트조회요청)로 직접 조회.
  토큰 발급(load_app_credentials/issue_access_token)은 get_kiwoom_ranking.py에
  이미 구현된 것을 그대로 재사용한다. 영웅문 화면과 같은 소스(키움) 원본이므로
  FinanceDataReader 대비 데이터 벤더 차이가 없다.
  (2026-08-19 기준: 키움 API가 "지정단말기 인증 실패"로 막혀 있어 당분간 fdr을 쓴다)
- fdr: 기존 FinanceDataReader 기반 조회.

STOCKS에 등록된 종목(삼성전자 + 시가총액 상위/업종 다양화 목적으로 고른 7개 종목,
backtest_multi.py의 다종목 백테스트 대상과 동일)을 --all로 한 번에 받거나,
--code로 종목 하나만 받을 수 있다.

사용법:
    python get_data.py                          # 키움 API로 삼성전자만 조회 (기본값)
    python get_data.py --source fdr              # FDR로 삼성전자만 조회
    python get_data.py --source fdr --all         # FDR로 STOCKS 전체 조회
    python get_data.py --source fdr --code 000660 # FDR로 SK하이닉스만 조회
"""

import argparse
import os
import re
import time
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd
import requests

# 키움 접근토큰 발급(load_app_credentials/issue_access_token)을 새로 만들지 않고
# 오늘 이미 만들어둔 get_kiwoom_ranking.py의 함수를 그대로 가져다 쓴다.
import get_kiwoom_ranking as kiwoom_ranking


# 수집 대상 종목. 삼성전자는 기존 파일 경로(data/samsung.csv)를 그대로 쓰고,
# 나머지는 시가총액 상위 + 업종 다양화(반도체/인터넷/2차전지/자동차/금융/바이오) 기준으로 골랐다.
# backtest_multi.py가 이 딕셔너리를 그대로 import해서 종목코드/이름/CSV 경로를 공유한다.
STOCKS = {
    "005930": {"name": "삼성전자", "output": "data/samsung.csv"},
    "000660": {"name": "SK하이닉스", "output": "data/price_000660.csv"},
    "035420": {"name": "NAVER", "output": "data/price_035420.csv"},
    "035720": {"name": "카카오", "output": "data/price_035720.csv"},
    "373220": {"name": "LG에너지솔루션", "output": "data/price_373220.csv"},
    "005380": {"name": "현대차", "output": "data/price_005380.csv"},
    "105560": {"name": "KB금융", "output": "data/price_105560.csv"},
    "207940": {"name": "삼성바이오로직스", "output": "data/price_207940.csv"},
}

# 실제 보유종목 9개. 005930/000660은 STOCKS와 종목이 겹쳐 같은 CSV 경로를 그대로 재사용한다.
# backtest_multi.py --group holdings가 이 딕셔너리를 그대로 import해서 쓴다.
HOLDINGS = {
    "005930": {"name": "삼성전자", "output": "data/samsung.csv"},
    "000660": {"name": "SK하이닉스", "output": "data/price_000660.csv"},
    "278470": {"name": "에이피알", "output": "data/price_278470.csv"},
    "010170": {"name": "대한광통신", "output": "data/price_010170.csv"},
    "034020": {"name": "두산에너빌리티", "output": "data/price_034020.csv"},
    "089030": {"name": "테크윙", "output": "data/price_089030.csv"},
    "090430": {"name": "아모레퍼시픽", "output": "data/price_090430.csv"},
    "329180": {"name": "HD현대중공업", "output": "data/price_329180.csv"},
    "267260": {"name": "HD현대일렉트릭", "output": "data/price_267260.csv"},
}

# 조회할 기간(일 단위). 5년 = 365일 * 5
LOOKBACK_DAYS = 365 * 5

# 키움 REST API - 주식일봉차트조회요청(ka10081)
KIWOOM_CHART_URL = f"{kiwoom_ranking.BASE_URL}/api/dostk/chart"
KIWOOM_TR_ID = "ka10081"

# 한 번 요청으로 받는 페이지 수에 안전장치를 둔다 (5년치를 받기에 충분한 여유).
# cont-yn이 계속 "Y"로 와도 이 페이지 수를 넘기면 강제로 멈춘다.
KIWOOM_MAX_PAGES = 30

# 연속 요청 사이에 최소한으로 둘 간격(초). API 과다 호출을 피하기 위한 것.
KIWOOM_REQUEST_INTERVAL = 0.3


def get_date_range():
    """
    오늘 날짜를 기준으로 최근 5년(LOOKBACK_DAYS일)에 해당하는
    시작일과 종료일 문자열(YYYY-MM-DD)을 반환한다.
    """
    end_date = datetime.today()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)

    # FinanceDataReader는 'YYYY-MM-DD' 형식의 문자열을 인자로 받는다
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def fetch_fdr_ohlcv(stk_cd: str, start_date: str, end_date: str):
    """
    FinanceDataReader를 이용해 종목의 일봉 시세 데이터를 가져온다.

    반환되는 DataFrame은 기본적으로 다음 컬럼을 포함한다:
    - Open  : 시가
    - High  : 고가
    - Low   : 저가
    - Close : 종가
    - Volume: 거래량
    - Change: 전일 대비 등락률

    인덱스는 거래일(Date, datetime 형식)이다.
    """
    df = fdr.DataReader(stk_cd, start_date, end_date)
    return df


def _parse_number(value) -> int:
    """
    키움 응답의 가격/거래량 필드를 정수로 변환한다.

    실시간 조회류 TR과 달리 일봉차트 데이터는 보통 부호 없는 순수 숫자 문자열이지만,
    혹시 "+253000"처럼 부호가 붙어 오거나 빈 문자열이 오는 경우에도 죽지 않도록
    숫자/부호 외의 문자를 제거한 뒤 변환한다.
    """
    s = str(value).strip()
    if not s:
        return 0
    cleaned = re.sub(r"[^0-9-]", "", s)
    if cleaned in ("", "-"):
        return 0
    return int(cleaned)


def fetch_kiwoom_daily_page(
    token: str,
    stk_cd: str,
    base_dt: str,
    upd_stkpc_tp: str = "1",
    cont_yn: str = "N",
    next_key: str = "",
):
    """
    ka10081(주식일봉차트조회요청) 한 페이지를 호출한다.

    send_daily_ranking.py/get_kiwoom_ranking.py가 쓰는 것과 같은 방식으로,
    cont-yn="Y"/next-key를 헤더에 실어 보내면 이전 응답에 이어 더 과거 데이터를
    받아올 수 있다(최초 호출은 cont-yn="N", next-key=""). 응답 JSON의 리스트 키
    이름이 정확히 확인되지 않은 상태를 대비해, "dt" 필드를 가진 딕셔너리 리스트를
    찾는 방식으로 리스트 키를 탐색한다(get_kiwoom_ranking.request_ranking()과
    같은 방어적 탐색 패턴).

    반환값: (일봉 데이터 행 리스트, 다음 페이지 존재 여부(cont-yn), next-key)
    """
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "cont-yn": cont_yn,
        "next-key": next_key,
        "api-id": KIWOOM_TR_ID,
    }
    payload = {
        "stk_cd": stk_cd,
        "base_dt": base_dt,
        "upd_stkpc_tp": upd_stkpc_tp,
    }

    response = requests.post(KIWOOM_CHART_URL, headers=headers, json=payload)
    print(f"[INFO] HTTP 상태 코드: {response.status_code}")
    response.raise_for_status()
    data = response.json()

    list_key = next(
        (
            k for k, v in data.items()
            if isinstance(v, list) and v and isinstance(v[0], dict) and "dt" in v[0]
        ),
        None,
    )
    if not list_key:
        print(f"[WARN] ka10081 응답에서 일봉 리스트를 찾지 못했습니다: {data}")
        return [], "N", ""

    rows = data[list_key]
    return rows, response.headers.get("cont-yn", "N"), response.headers.get("next-key", "")


def fetch_kiwoom_daily_ohlcv(
    token: str,
    stk_cd: str,
    lookback_days: int = LOOKBACK_DAYS,
    upd_stkpc_tp: str = "1",
) -> pd.DataFrame:
    """
    ka10081을 cont-yn/next-key로 계속 이어붙여 최근 lookback_days일치 일봉 데이터를
    모은 뒤, FinanceDataReader 결과와 같은 형식(Date 인덱스, Open/High/Low/Close/
    Volume/Change 컬럼)의 DataFrame으로 돌려준다. save_to_csv()가 소스에 관계없이
    그대로 동작하도록 컬럼 구조를 fetch_fdr_ohlcv()의 반환값과 맞춘 것이다.
    """
    end_date = datetime.today()
    start_date = end_date - timedelta(days=lookback_days)
    start_dt_str = start_date.strftime("%Y%m%d")
    base_dt = end_date.strftime("%Y%m%d")

    all_rows = []
    cont_yn, next_key = "N", ""
    for page in range(1, KIWOOM_MAX_PAGES + 1):
        print(f"[INFO] ka10081({stk_cd}) 일봉 조회 {page}페이지째 (cont-yn={cont_yn})...")
        rows, cont_yn, next_key = fetch_kiwoom_daily_page(
            token, stk_cd, base_dt,
            upd_stkpc_tp=upd_stkpc_tp,
            cont_yn=cont_yn,
            next_key=next_key,
        )
        if not rows:
            break
        all_rows.extend(rows)

        oldest_dt = min(row.get("dt", "99999999") for row in rows)
        if oldest_dt <= start_dt_str or cont_yn != "Y":
            break

        time.sleep(KIWOOM_REQUEST_INTERVAL)

    if not all_rows:
        raise ValueError(f"ka10081 응답에서 {stk_cd} 일봉 데이터를 하나도 받지 못했습니다.")

    # 페이지 경계에서 같은 날짜가 중복으로 올 수 있어 dt를 key로 삼아 중복 제거한다
    by_date = {row["dt"]: row for row in all_rows if row.get("dt")}

    df = pd.DataFrame([
        {
            "Date": datetime.strptime(dt, "%Y%m%d"),
            "Open": _parse_number(row.get("open_pric")),
            "High": _parse_number(row.get("high_pric")),
            "Low": _parse_number(row.get("low_pric")),
            "Close": _parse_number(row.get("cur_prc")),
            "Volume": _parse_number(row.get("trde_qty")),
        }
        for dt, row in by_date.items()
    ])

    df = df.sort_values("Date").set_index("Date")
    df = df[df.index >= start_date]
    df["Change"] = df["Close"].pct_change()

    return df


def save_to_csv(df, output_path: str):
    """
    수집한 데이터프레임을 CSV 파일로 저장한다.
    저장 경로의 상위 디렉터리가 없으면 자동으로 생성한다.
    """
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 인덱스(날짜)도 함께 저장하기 위해 index=True 사용
    # 한글 데이터가 깨지지 않도록 encoding을 utf-8-sig로 지정 (엑셀 호환)
    df.to_csv(output_path, index=True, encoding="utf-8-sig")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="종목 일봉 데이터 수집 (키움 REST API 또는 FinanceDataReader)")
    parser.add_argument("--source", choices=["kiwoom", "fdr"], default="kiwoom", help="데이터 소스 (기본값 kiwoom)")
    parser.add_argument("--code", default="005930", help="종목코드 (기본값 005930=삼성전자). --all/--holdings와 함께 쓰면 무시된다")
    parser.add_argument("--all", action="store_true", help="STOCKS에 등록된 전체 종목을 한 번에 조회")
    parser.add_argument("--holdings", action="store_true", help="HOLDINGS(실제 보유종목)에 등록된 전체 종목을 한 번에 조회")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.holdings:
        registry = HOLDINGS
        codes = list(HOLDINGS.keys())
    elif args.all:
        registry = STOCKS
        codes = list(STOCKS.keys())
    else:
        registry = STOCKS
        codes = [args.code]

    # 키움 토큰은 여러 종목을 조회하더라도 한 번만 발급받아 재사용한다
    # (send_daily_ranking.py가 순위 3종 조회에 토큰 하나를 공용으로 쓰는 것과 같은 방식)
    token = None
    if args.source == "kiwoom":
        app_key, secret_key = kiwoom_ranking.load_app_credentials()
        token = kiwoom_ranking.issue_access_token(app_key, secret_key)

    for code in codes:
        info = registry.get(code, {})
        name = info.get("name", code)
        output_path = info.get("output", f"data/price_{code}.csv")

        if args.source == "fdr":
            start_date, end_date = get_date_range()
            print(f"[INFO] {name}({code}) 일봉 데이터 조회 기간(FDR): {start_date} ~ {end_date}")
            df = fetch_fdr_ohlcv(code, start_date, end_date)
        else:
            print(f"[INFO] {name}({code}) 일봉 데이터 조회(키움 ka10081, 최근 {LOOKBACK_DAYS}일)...")
            df = fetch_kiwoom_daily_ohlcv(token, code, lookback_days=LOOKBACK_DAYS)

        print(f"[INFO] 수집된 데이터 행 수: {len(df)}")

        save_to_csv(df, output_path)
        print(f"[INFO] 데이터 저장 완료: {output_path}")


if __name__ == "__main__":
    main()
