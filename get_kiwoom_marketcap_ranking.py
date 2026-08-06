"""
키움증권 REST API ka10099(종목정보 리스트)를 이용해 시가총액상위 종목을 조회하는 스크립트.

ka10099는 "순위" TR이 아니라 시장별 전체 종목 목록을 반환하는 TR이라
(순위정보 그룹에는 시가총액상위 전용 TR이 없음. ka10030/ka10032 조회 시 확인했던 내용과 동일)
직접 시가총액(=상장주식수 x 현재가)을 계산해서 정렬해야 한다.

흐름:
1. .env에서 KIWOOM_APP_KEY/KIWOOM_SECRET_KEY로 접근토큰을 새로 발급받아 .env에 저장한다.
2. ka10099를 KOSPI(mrkt_tp=0)와 KOSDAQ(mrkt_tp=10) 두 번 호출해 전체 종목을 모은다.
   (ka10099는 시장별로만 조회 가능하고 "전체" 옵션이 없음)
3. marketName이 '거래소'/'코스닥'인 것만 남겨 ETF/ETN/리츠 등을 제외하고,
   종목명이 '우'/'우B'로 끝나는 우선주도 제외한다.
4. 남은 종목의 시가총액(listCount x lastPrice)을 계산해 내림차순 정렬 후 상위 N개를 출력한다.
"""

import os
import sys

import requests
from dotenv import load_dotenv, set_key

sys.stdout.reconfigure(encoding="utf-8")

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

BASE_URL = "https://api.kiwoom.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
STKINFO_URL = f"{BASE_URL}/api/dostk/stkinfo"

# 시장구분: 0=거래소(KOSPI), 10=코스닥
MARKETS = {"0": "KOSPI", "10": "KOSDAQ"}

# marketName이 이 값이 아니면 ETF/ETN/리츠/인프라투자금융/뮤추얼펀드 등이므로 제외
COMMON_MARKET_NAMES = {"거래소", "코스닥"}


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


def request_stock_list(token: str, mrkt_tp: str) -> list[dict]:
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "cont-yn": "N",
        "next-key": "",
        "api-id": "ka10099",
    }
    response = requests.post(STKINFO_URL, headers=headers, json={"mrkt_tp": mrkt_tp})
    response.raise_for_status()
    data = response.json()
    return data.get("list", [])


def is_common_stock(item: dict) -> bool:
    if item.get("marketName") not in COMMON_MARKET_NAMES:
        return False  # ETF/ETN/리츠 등 제외
    name = item.get("name", "")
    if name.endswith("우") or name.endswith("우B"):
        return False  # 우선주 제외
    return True


def main():
    app_key, secret_key = load_app_credentials()
    token = issue_access_token(app_key, secret_key)

    all_items = []
    for mrkt_tp, label in MARKETS.items():
        print(f"[INFO] ka10099(종목정보 리스트) {label}(mrkt_tp={mrkt_tp}) 조회 중...")
        items = request_stock_list(token, mrkt_tp)
        print(f"[INFO] {label} {len(items)}건 수신")
        all_items.extend(items)

    common = [item for item in all_items if is_common_stock(item)]
    print(f"[INFO] 전체 {len(all_items)}건 -> ETF/ETN/우선주 제외 후 {len(common)}건")

    for item in common:
        item["market_cap"] = int(item["listCount"]) * int(item["lastPrice"])

    ranked = sorted(common, key=lambda x: x["market_cap"], reverse=True)

    print("\n상위 5개 (시가총액 기준, 단위: 억원):\n")
    print(f"{'순위':<4}{'종목명':<20}{'종목코드':<10}{'현재가':>10}{'시가총액':>16}")
    for i, item in enumerate(ranked[:5], start=1):
        cap_eok = item["market_cap"] // 100_000_000
        print(
            f"{i:<4}{item['name']:<20}{item['code']:<10}"
            f"{int(item['lastPrice']):>10}{cap_eok:>16,}"
        )


if __name__ == "__main__":
    main()
