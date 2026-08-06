"""
키움증권 REST API 앱키(KIWOOM_APP_KEY)/시크릿키(KIWOOM_SECRET_KEY)가
정상적으로 동작하는지 확인하는 스크립트.

키움 REST API는 별도의 로그인 절차 없이, 미리 발급받은 앱키/시크릿키로
client_credentials 방식의 접근토큰(access token)을 발급받는 구조다.
이 요청이 성공하면 키가 유효하다는 뜻이고, 실패하면 키가 잘못되었거나
API 사용 신청이 안 되어 있다는 뜻이다.
"""

import os
import sys

import requests
from dotenv import load_dotenv

# Windows 콘솔(cp949) 환경에서 이모지/특수문자 출력 시 UnicodeEncodeError가 나는 것을 방지
sys.stdout.reconfigure(encoding="utf-8")

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# 실전투자 도메인 (모의투자는 https://mockapi.kiwoom.com)
TOKEN_URL = "https://api.kiwoom.com/oauth2/token"


def load_credentials() -> tuple[str, str]:
    load_dotenv(dotenv_path=ENV_PATH)

    app_key = os.getenv("KIWOOM_APP_KEY")
    secret_key = os.getenv("KIWOOM_SECRET_KEY")

    if not app_key or not secret_key:
        raise ValueError(
            ".env 파일에 KIWOOM_APP_KEY 또는 KIWOOM_SECRET_KEY 값이 비어 있습니다."
        )

    return app_key, secret_key


def request_access_token(app_key: str, secret_key: str) -> dict:
    headers = {"Content-Type": "application/json;charset=UTF-8"}
    payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": secret_key,
    }

    response = requests.post(TOKEN_URL, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()


def mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def main():
    app_key, secret_key = load_credentials()

    print("[INFO] 키움 REST API 접근토큰 발급을 요청합니다...")
    try:
        token_data = request_access_token(app_key, secret_key)
    except requests.exceptions.HTTPError as e:
        print(f"[FAIL] HTTP 오류: {e}")
        print(f"[FAIL] 응답 본문: {e.response.text}")
        return
    except requests.exceptions.RequestException as e:
        print(f"[FAIL] 요청 실패: {e}")
        return

    token = token_data.get("token")
    return_code = token_data.get("return_code")

    if token:
        print("[OK] 접근토큰 발급 성공 — 키움 API 키가 정상 동작합니다.")
        print(f"[OK] token(마스킹): {mask(token)}")
        print(f"[OK] token_type: {token_data.get('token_type')}")
        print(f"[OK] expires_dt: {token_data.get('expires_dt')}")
    else:
        print("[FAIL] 접근토큰 발급 실패")
        print(f"[FAIL] return_code: {return_code}, return_msg: {token_data.get('return_msg')}")


if __name__ == "__main__":
    main()
