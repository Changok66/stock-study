"""
키움증권 REST API "계좌번호조회"(ka00001) TR을 호출해 계좌번호를 조회하고,
그 값을 .env 파일의 KIWOOM_ACCOUNT_NO에 그대로 저장하는 스크립트.

TR 코드:
- ka00001: 계좌번호조회 (국내주식 > 계좌 그룹, /api/dostk/acnt)
  요청 바디(payload) 없이 헤더만으로 호출하며, 응답의 'acctNo' 필드에
  계좌번호(10자리 숫자 + 사내 분류용 뒤 2자리)가 담겨 온다.

흐름 (get_kiwoom_ranking.py와 동일한 패턴):
1. .env에서 KIWOOM_APP_KEY/KIWOOM_SECRET_KEY를 읽어 접근토큰(access token)을 새로 발급받고,
   KIWOOM_ACCESS_TOKEN으로 .env에 저장한다.
2. 발급받은 토큰으로 ka00001(계좌번호조회)을 호출한다.
3. 응답의 acctNo 값을 그대로 .env의 KIWOOM_ACCOUNT_NO에 저장한다.

사용법:
    python get_kiwoom_account_no.py
"""

import os
import sys

import requests
from dotenv import load_dotenv, set_key

# Windows 콘솔(cp949) 환경에서 한글/특수문자 출력 시 깨지는 것을 방지
sys.stdout.reconfigure(encoding="utf-8")

# 이 스크립트 파일과 같은 폴더에 있는 .env 파일 경로를 구한다
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

BASE_URL = "https://api.kiwoom.com"
TOKEN_URL = f"{BASE_URL}/oauth2/token"
ACCOUNT_URL = f"{BASE_URL}/api/dostk/acnt"  # ka00001(계좌번호조회)이 속한 "계좌" 그룹 엔드포인트

TR_ID = "ka00001"


def load_app_credentials() -> tuple[str, str]:
    """.env 파일에서 앱키/시크릿키를 읽어온다."""
    load_dotenv(dotenv_path=ENV_PATH)
    app_key = os.getenv("KIWOOM_APP_KEY")
    secret_key = os.getenv("KIWOOM_SECRET_KEY")
    if not app_key or not secret_key:
        raise ValueError(".env에 KIWOOM_APP_KEY/KIWOOM_SECRET_KEY가 없습니다.")
    return app_key, secret_key


def issue_access_token(app_key: str, secret_key: str) -> str:
    """앱키/시크릿키로 접근토큰을 새로 발급받고, .env에도 저장해둔다."""
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

    # 다음 실행 때 재사용할 수 있도록 .env에도 저장해둔다
    set_key(ENV_PATH, "KIWOOM_ACCESS_TOKEN", token)
    set_key(ENV_PATH, "KIWOOM_TOKEN_EXPIRES_DT", str(data.get("expires_dt")))
    print(f"[INFO] 접근토큰 발급 및 .env 저장 완료 (만료: {data.get('expires_dt')})")
    return token


def request_account_no(token: str) -> dict:
    """ka00001(계좌번호조회)을 호출한다. 요청 바디는 비어있다."""
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "cont-yn": "N",
        "next-key": "",
        "api-id": TR_ID,
    }
    response = requests.post(ACCOUNT_URL, headers=headers, json={})
    print(f"[INFO] HTTP 상태 코드: {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        print(f"[FAIL] JSON 파싱 실패, 원문: {response.text}")
        raise
    return data


def main():
    app_key, secret_key = load_app_credentials()
    token = issue_access_token(app_key, secret_key)

    print(f"[INFO] {TR_ID}(계좌번호조회) 조회 중...")
    data = request_account_no(token)

    print(f"[DEBUG] return_code: {data.get('return_code')}, return_msg: {data.get('return_msg')}")

    account_no = data.get("acctNo")
    if not account_no:
        print("[FAIL] 응답에서 acctNo 값을 찾지 못했습니다. 전체 응답:")
        print(data)
        return

    # 조회된 계좌번호를 그대로 .env의 KIWOOM_ACCOUNT_NO에 저장한다
    set_key(ENV_PATH, "KIWOOM_ACCOUNT_NO", account_no)
    print(f"[OK] 계좌번호 조회 및 .env 저장 완료: {account_no}")


if __name__ == "__main__":
    main()
