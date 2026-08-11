"""
키움증권 REST API "순위정보"/"종목정보" 그룹의 TR을 호출해 순위 데이터를 조회하는 스크립트.

관련 TR 코드:
- ka10030: 당일거래량상위요청 (국내주식 > 순위정보, jobTpCode=05 그룹, /api/dostk/rkinfo)
- ka10031: 전일거래량상위요청 (위와 동일 그룹/엔드포인트)
- ka10032: 거래대금상위요청 (위와 동일 그룹/엔드포인트)
- ka00198: 실시간종목조회순위 (국내주식 > 종목정보 그룹, /api/dostk/stkinfo)  <- 이 스크립트가 실제로 호출하는 TR
  거래량/거래대금이 아니라 "실시간 조회(관심) 빈도" 기준 순위이며, 응답 구조가
  ka10030/ka10032와 다르다 (거래량·거래대금·현재가 필드가 없고, 대신
  기준가 대비 등락율/순위 등락 정보를 제공한다). request_ranking()에서
  TR_ID에 따라 요청 URL/payload를 분기 처리한다.
- (참고) "시가총액상위"에 해당하는 전용 순위 TR은 이 그룹에 없음.
  시가총액은 ka10099(종목정보 리스트) 등 종목정보 조회 TR의 응답 필드로만 제공됨.

흐름:
1. .env에서 KIWOOM_APP_KEY/KIWOOM_SECRET_KEY를 읽어 접근토큰(access token)을 새로 발급받고,
   KIWOOM_ACCESS_TOKEN으로 .env에 저장한다 (다음 실행 때 재사용할 수 있도록).
2. 발급받은 토큰으로 지정한 순위 TR(기본값 ka00198)을 호출한다.
3. 응답에서 순위 리스트를 추려 상위 N개만 출력한다.

사용법:
    python get_kiwoom_ranking.py            # ka00198 실시간종목조회순위
    python get_kiwoom_ranking.py ka10032    # 거래대금상위
"""

import os
import sys

import requests
from dotenv import load_dotenv, set_key

sys.stdout.reconfigure(encoding="utf-8")

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

BASE_URL = "https://api.kiwoom.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
RANKING_URL = f"{BASE_URL}/api/dostk/rkinfo"      # ka10030/ka10031/ka10032 (순위정보 그룹)
STKINFO_URL = f"{BASE_URL}/api/dostk/stkinfo"     # ka00198 (종목정보 그룹)

TR_NAMES = {
    "ka10030": "당일거래량상위요청",
    "ka10031": "전일거래량상위요청",
    "ka10032": "거래대금상위요청",
    "ka00198": "실시간종목조회순위",
}

TR_ID = sys.argv[1] if len(sys.argv) > 1 else "ka00198"


def load_app_credentials() -> tuple[str, str]:
    load_dotenv(dotenv_path=ENV_PATH)
    app_key = os.getenv("KIWOOM_APP_KEY")
    secret_key = os.getenv("KIWOOM_SECRET_KEY")
    if not app_key or not secret_key:
        raise ValueError(".env에 KIWOOM_APP_KEY/KIWOOM_SECRET_KEY가 없습니다.")
    return app_key, secret_key


def issue_access_token(app_key: str, secret_key: str) -> str:
    headers = {"Content-Type": "application/json;charset=UTF-8"}
    payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": secret_key,
    }
    response = requests.post(TOKEN_URL, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()

    token = data.get("token")
    if not token:
        raise ValueError(f"토큰 발급 실패: {data}")

    set_key(ENV_PATH, "KIWOOM_ACCESS_TOKEN", token)
    set_key(ENV_PATH, "KIWOOM_TOKEN_EXPIRES_DT", str(data.get("expires_dt")))
    print(f"[INFO] 접근토큰 발급 및 .env 저장 완료 (만료: {data.get('expires_dt')})")
    return token


def request_ranking(token: str) -> dict:
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "cont-yn": "N",
        "next-key": "",
        "api-id": TR_ID,
    }

    if TR_ID == "ka00198":
        # ka00198(실시간종목조회순위)은 순위정보 그룹(ka10030 등)과 엔드포인트/요청
        # 파라미터가 전혀 다르다. 요청 바디는 qry_tp 하나뿐이며,
        # 1:1분, 2:10분, 3:1시간, 4:당일 누적, 5:30초 중 하나를 고른다.
        # "당일 상위" 성격에 맞춰 4(당일 누적)를 사용한다.
        url = STKINFO_URL
        payload = {"qry_tp": "4"}
    else:
        # 시장 전체 / 거래량 기준 정렬 / ETF+ETN 제외 / 통합거래소 기준으로 조회
        url = RANKING_URL
        payload = {
            "mrkt_tp": "000",       # 시장구분: 000=전체
            "sort_tp": "1",         # 정렬구분: 1=거래량
            "mang_stk_incls": "16", # 종목필터: 16=ETF+ETN 제외
            "crd_tp": "0",          # 신용구분: 0=전체
            "trde_qty_tp": "0",     # 거래량구분: 0=전체
            "pric_tp": "0",         # 가격구분: 0=전체
            "trde_prica_tp": "0",   # 거래대금구분: 0=전체
            "mrkt_open_tp": "0",    # 장운영구분: 0=전체
            "stex_tp": "3",         # 거래소구분: 3=통합(KRX+NXT)
        }

    response = requests.post(url, headers=headers, json=payload)
    print(f"[INFO] HTTP 상태 코드: {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        print(f"[FAIL] JSON 파싱 실패, 원문: {response.text}")
        raise
    return data


# 국내 주요 ETF/ETN 브랜드 접두어. mang_stk_incls=16(ETF+ETN제외) 옵션이 TR에 따라
# 제대로 먹지 않는 경우가 있어(ka10032에서 확인됨), 이름 기반으로 한 번 더 걸러낸다.
ETF_ETN_PREFIXES = (
    "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO", "KINDEX", "SOL", "ACE",
    "PLUS", "RISE", "WOORI", "TIMEFOLIO", "KOSEF", "마이다스", "파워", "히어로즈",
    "신한", "FOCUS", "ITF", "마이티", "VITA", "KTOP", "HK", "대신343",
)


def is_common_stock(name: str) -> bool:
    """ETF/ETN(주요 브랜드 접두어) 및 우선주(이름이 '우'/'우B'로 끝남)를 제외한다."""
    if any(name.startswith(prefix) for prefix in ETF_ETN_PREFIXES):
        return False
    if name.endswith("우") or name.endswith("우B"):
        return False
    return True


def main():
    app_key, secret_key = load_app_credentials()
    token = issue_access_token(app_key, secret_key)

    tr_name = TR_NAMES.get(TR_ID, "알 수 없는 TR")
    print(f"[INFO] {TR_ID}({tr_name}) 조회 중...")
    data = request_ranking(token)

    print(f"[DEBUG] return_code: {data.get('return_code')}, return_msg: {data.get('return_msg')}")

    # 응답 body의 리스트 필드 키는 TR마다 다를 수 있어 dict/list 타입 값을 가진 키를 탐색
    list_key = None
    for k, v in data.items():
        if isinstance(v, list) and v:
            list_key = k
            break

    if not list_key:
        print("[FAIL] 응답에서 리스트 데이터를 찾지 못했습니다. 전체 응답:")
        print(data)
        return

    item0 = data[list_key][0]

    # ka00198(실시간종목조회순위)에는 cur_prc/flu_rt가 없고 대신
    # past_curr_prc(기준시점 가격)/base_comp_chgr(기준가 대비 등락율)가 온다
    price_field = "cur_prc" if "cur_prc" in item0 else "past_curr_prc"
    rate_field = "flu_rt" if "flu_rt" in item0 else "base_comp_chgr"

    # TR마다 거래량/거래대금 필드명이 다르므로(trde_qty, now_trde_qty, trde_prica 등)
    # 존재하는 필드를 우선순위대로 찾아서 사용한다. ka00198처럼 거래량/거래대금
    # 자체가 없는 TR은 대신 순위 등락(rank_chg_sign)을 보여준다.
    qty_field = next(
        (f for f in ("trde_qty", "now_trde_qty", "trde_prica") if f in item0),
        None,
    )
    if qty_field:
        qty_label = "거래대금" if qty_field == "trde_prica" else "거래량"
    else:
        qty_field = "rank_chg_sign" if "rank_chg_sign" in item0 else None
        qty_label = "순위등락"

    filtered = [item for item in data[list_key] if is_common_stock(item.get("stk_nm", ""))]
    print(
        f"[INFO] 리스트 필드명: '{list_key}', 전체 {len(data[list_key])}건 -> "
        f"우선주 제외 후 {len(filtered)}건 중 상위 5개:\n"
    )
    print(f"{'순위':<4}{'종목명':<22}{'종목코드':<12}{'현재가':>10}{'등락률':>10}{qty_label:>16}")
    for i, item in enumerate(filtered[:5], start=1):
        qty = item.get(qty_field, "") if qty_field else ""
        print(
            f"{i:<4}{item.get('stk_nm', ''):<22}{item.get('stk_cd', ''):<12}"
            f"{item.get(price_field, ''):>10}{item.get(rate_field, ''):>9}%"
            f"{qty:>16}"
        )


if __name__ == "__main__":
    main()
