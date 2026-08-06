"""
카카오톡 "나에게 보내기" 메시지 전송에 필요한 액세스 토큰을 발급받는 스크립트.

전체 흐름(카카오 인가 코드 받기 -> 액세스 토큰으로 교환 -> .env에 저장):
1. .env 파일에서 REST API 키(KAKAO_REST_API_KEY)와, 설정되어 있다면
   Client Secret(KAKAO_CLIENT_SECRET)을 읽어온다.
2. 사용자가 브라우저에서 로그인/동의할 수 있도록 카카오 인증 URL을 출력한다.
3. 로그인 후 리다이렉트된 주소(redirect_uri?code=...)에서 code= 뒤의
   인가 코드를 사용자가 직접 복사해서 입력하도록 한다.
4. 인가 코드로 토큰 발급 API를 호출해 액세스 토큰과 리프레시 토큰을 받는다.
5. 발급받은 토큰을 KAKAO_ACCESS_TOKEN / KAKAO_REFRESH_TOKEN이라는 이름으로
   .env 파일에 추가/갱신한다.

주의:
- redirect_uri는 카카오 개발자 콘솔의 "Redirect URI" 등록값과 정확히 일치해야 한다.
  (여기서는 https://localhost:5000 사용)
- Client Secret은 카카오 개발자 콘솔의 "카카오 로그인 > 보안"에서 사용 설정을
  켠 경우에만 필요하다. KAKAO_CLIENT_SECRET이 비어 있으면 요청에서 생략된다.
- 이 스크립트는 실제로 브라우저를 열거나 서버를 띄우지 않는다.
  사용자가 URL을 직접 열고, 리다이렉트된 주소를 눈으로 보고 코드를 복사해서
  입력하는 수동 방식이다.
"""

import os

import requests
from dotenv import load_dotenv, set_key

# .env 파일 경로 (이 스크립트와 같은 폴더에 있다고 가정)
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# 카카오 로그인/토큰 관련 고정 URL
KAKAO_AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"

# 카카오 개발자 콘솔에 등록해 둔 Redirect URI (문제에서 지정한 값)
REDIRECT_URI = "https://localhost:5000"


def load_rest_api_key() -> str:
    """
    .env 파일을 읽어서 KAKAO_REST_API_KEY 값을 반환한다.
    python-dotenv의 load_dotenv()로 .env 내용을 환경 변수로 로드한 뒤,
    os.getenv()로 값을 꺼내온다.
    """
    load_dotenv(dotenv_path=ENV_PATH)

    rest_api_key = os.getenv("KAKAO_REST_API_KEY")
    if not rest_api_key:
        # 키가 비어 있으면 이후 단계를 진행할 수 없으므로 바로 에러를 발생시킨다
        raise ValueError(
            ".env 파일에 KAKAO_REST_API_KEY 값이 비어 있습니다. "
            "먼저 카카오 개발자 콘솔에서 발급받은 REST API 키를 채워주세요."
        )

    return rest_api_key


def load_client_secret() -> str | None:
    """
    .env 파일에서 KAKAO_CLIENT_SECRET 값을 읽어온다.

    카카오 개발자 콘솔에서 Client Secret 사용을 켜지 않았다면 값이 없을 수 있으므로,
    비어 있으면 None을 반환해 이후 토큰 요청에서 해당 값을 생략하도록 한다.
    """
    load_dotenv(dotenv_path=ENV_PATH)
    client_secret = os.getenv("KAKAO_CLIENT_SECRET")
    return client_secret if client_secret else None


def print_authorize_url(rest_api_key: str) -> None:
    """
    사용자가 브라우저에서 열어야 하는 카카오 로그인 인증 URL을 출력한다.

    이 URL에 접속해 로그인/동의를 완료하면 카카오가 REDIRECT_URI로
    "code=인가코드" 형태의 쿼리 파라미터를 붙여 리다이렉트시켜 준다.
    """
    # response_type=code : 인가 코드 방식(Authorization Code Grant)을 사용한다는 의미
    auth_url = (
        f"{KAKAO_AUTHORIZE_URL}"
        f"?client_id={rest_api_key}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
    )

    print("[INFO] 아래 URL을 브라우저에서 열어 카카오 로그인 및 동의를 진행하세요.")
    print(auth_url)
    print()
    print(
        "[INFO] 로그인 후 리다이렉트되는 주소창을 확인하면 "
        f"'{REDIRECT_URI}/?code=...' 형태로 표시됩니다."
    )
    print("[INFO] 그 중 'code=' 뒤에 있는 인가 코드 값을 복사해서 아래에 입력해주세요.")


def input_authorization_code() -> str:
    """
    사용자로부터 인가 코드를 직접 입력받는다.

    리다이렉트된 전체 주소(예: https://localhost:5000/?code=abcd1234)를 붙여넣어도
    'code=' 뒤의 값만 잘라서 사용할 수 있도록 처리한다.
    """
    user_input = input("인가 코드(또는 리다이렉트된 전체 주소)를 입력하세요: ").strip()

    # 사용자가 전체 URL을 그대로 붙여넣은 경우, code= 뒤의 값만 추출한다
    if "code=" in user_input:
        code = user_input.split("code=")[-1]
        # 뒤에 다른 쿼리 파라미터(&state= 등)가 붙어있을 수 있으므로 & 이전까지만 사용
        code = code.split("&")[0]
    else:
        # 인가 코드만 입력한 경우 그대로 사용
        code = user_input

    if not code:
        raise ValueError("인가 코드가 비어 있습니다. 올바른 값을 입력해주세요.")

    return code


def request_access_token(
    rest_api_key: str, authorization_code: str, client_secret: str | None = None
) -> dict:
    """
    인가 코드를 이용해 카카오 토큰 발급 API를 호출하고 응답 전체(dict)를 반환한다.
    (access_token, refresh_token 등이 포함됨)
    """
    # 카카오 토큰 발급 API는 application/x-www-form-urlencoded 형식의
    # POST 요청을 요구한다 (requests의 data= 인자를 사용하면 자동으로 처리됨)
    payload = {
        "grant_type": "authorization_code",
        "client_id": rest_api_key,
        "redirect_uri": REDIRECT_URI,
        "code": authorization_code,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    response = requests.post(KAKAO_TOKEN_URL, data=payload)

    # 요청이 실패(4xx, 5xx)하면 예외를 발생시켜 문제를 바로 알 수 있도록 한다
    response.raise_for_status()

    token_data = response.json()

    if not token_data.get("access_token"):
        raise ValueError(f"응답에서 access_token을 찾을 수 없습니다: {token_data}")

    return token_data


def save_tokens_to_env(token_data: dict) -> None:
    """
    발급받은 액세스/리프레시 토큰을 .env 파일에 저장한다.

    python-dotenv의 set_key()를 사용하면:
    - 해당 키가 이미 있으면 값을 갱신하고,
    - 없으면 파일 맨 뒤에 새로 추가해준다.

    리프레시 토큰(KAKAO_REFRESH_TOKEN)을 저장해 두면, 액세스 토큰이 만료되었을 때
    (약 12시간) 브라우저 로그인 없이 다시 발급받을 수 있다.
    """
    set_key(ENV_PATH, "KAKAO_ACCESS_TOKEN", token_data["access_token"])
    print(f"[INFO] KAKAO_ACCESS_TOKEN 값을 .env 파일에 저장했습니다: {ENV_PATH}")

    refresh_token = token_data.get("refresh_token")
    if refresh_token:
        set_key(ENV_PATH, "KAKAO_REFRESH_TOKEN", refresh_token)
        print(f"[INFO] KAKAO_REFRESH_TOKEN 값을 .env 파일에 저장했습니다: {ENV_PATH}")


def main():
    # 1. .env에서 REST API 키와 Client Secret(있다면) 읽기
    rest_api_key = load_rest_api_key()
    client_secret = load_client_secret()

    # 2. 카카오 로그인 인증 URL 출력
    print_authorize_url(rest_api_key)

    # 3. 사용자로부터 인가 코드 입력받기
    authorization_code = input_authorization_code()

    # 4. 인가 코드로 액세스 토큰 요청
    print("[INFO] 액세스 토큰을 요청하는 중입니다...")
    token_data = request_access_token(rest_api_key, authorization_code, client_secret)
    print("[INFO] 액세스 토큰 발급 완료")

    # 5. 발급받은 토큰을 .env 파일에 저장
    save_tokens_to_env(token_data)


if __name__ == "__main__":
    main()
