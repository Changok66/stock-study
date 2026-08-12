"""
카카오톡 "나에게 보내기" API로 텍스트 메시지를 전송하는 스크립트.

전체 흐름:
1. .env 파일에서 KAKAO_ACCESS_TOKEN 값을 읽어온다.
   (이 토큰은 get_kakao_token.py 스크립트로 미리 발급받아 .env에 저장해둔 것을 사용한다)
2. 카카오 "나에게 보내기" API(POST /v2/api/talk/memo/default/send)를 호출한다.
3. 이 API는 template_object라는 이름의 JSON 파라미터로 메시지 형식을 지정해야 하며,
   여기서는 가장 단순한 형태인 "텍스트(Text) 템플릿"을 사용한다.
4. 요청이 성공하면 성공 메시지를 출력하고, 실패하면 예외를 통해 에러 내용이 드러난다.

주의:
- KAKAO_ACCESS_TOKEN은 발급 후 약 12시간이 지나면 만료된다.
  만료된 경우 get_kakao_token.py를 다시 실행해 토큰을 재발급받아야 한다.
  (또는 아래 refresh_access_token()으로 KAKAO_REFRESH_TOKEN을 이용해 브라우저 로그인 없이
  재발급받을 수 있다. send_daily_ranking.py/watch_trades.py는 실행할 때마다 이 함수를
  호출해 액세스 토큰을 미리 갱신해두므로 만료 걱정 없이 쓸 수 있다)
- "나에게 보내기" 기능을 사용하려면 카카오 개발자 콘솔에서 해당 앱에
  "카카오톡 메시지 전송" 동의항목(talk_message)이 활성화되어 있어야 한다.
"""

import json
import os

import requests
from dotenv import load_dotenv, set_key

# .env 파일 경로 (이 스크립트와 같은 폴더에 있다고 가정)
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# 카카오 "나에게 보내기" 메시지 전송 API 주소
KAKAO_MEMO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

# 카카오 토큰 발급/재발급 API 주소 (get_kakao_token.py의 최초 발급과 동일한 엔드포인트)
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"

# 실제로 전송할 메시지 내용 (요청받은 고정 텍스트)
MESSAGE_TEXT = "테스트 메시지입니다"


def load_access_token() -> str:
    """
    .env 파일을 읽어서 KAKAO_ACCESS_TOKEN 값을 반환한다.

    python-dotenv의 load_dotenv()는 .env 파일의 내용을 현재 프로세스의
    환경 변수로 로드해주고, 이후 os.getenv()로 해당 값을 꺼내올 수 있다.
    """
    load_dotenv(dotenv_path=ENV_PATH)

    access_token = os.getenv("KAKAO_ACCESS_TOKEN")
    if not access_token:
        # 토큰이 비어 있으면 API 호출 자체가 불가능하므로 바로 에러를 발생시켜
        # 원인을 명확히 알 수 있게 한다
        raise ValueError(
            ".env 파일에 KAKAO_ACCESS_TOKEN 값이 비어 있습니다. "
            "먼저 get_kakao_token.py를 실행해 액세스 토큰을 발급받아주세요."
        )

    return access_token


def refresh_access_token() -> str:
    """
    .env의 KAKAO_REFRESH_TOKEN으로 카카오 토큰 재발급 API를 호출해 새 액세스 토큰을 받고,
    .env의 KAKAO_ACCESS_TOKEN을 그 값으로 갱신한 뒤 새 액세스 토큰 문자열을 반환한다.

    get_kakao_token.py의 최초 발급(브라우저 로그인 필요)과 달리, 리프레시 토큰만 있으면
    브라우저 상호작용 없이 재발급받을 수 있다. KAKAO_ACCESS_TOKEN은 발급 후 약 12시간이면
    만료되므로, 호출하는 쪽(send_daily_ranking.py/watch_trades.py)에서 실행할 때마다 이
    함수를 먼저 호출해 항상 새 액세스 토큰으로 전송하도록 한다.

    카카오는 리프레시 토큰 자체도 유효기간이 있어(발급 후 2개월, 액세스 토큰 유효기간의
    절반 미만으로 남으면), 응답에 새 refresh_token이 함께 내려올 때가 있다. 그 경우 함께
    갱신해 두지 않으면 다음 재발급 때 예전 리프레시 토큰을 써서 실패할 수 있으므로, 응답에
    refresh_token이 포함돼 있으면 KAKAO_REFRESH_TOKEN도 함께 갱신한다.
    """
    load_dotenv(dotenv_path=ENV_PATH)

    rest_api_key = os.getenv("KAKAO_REST_API_KEY")
    client_secret = os.getenv("KAKAO_CLIENT_SECRET")
    refresh_token = os.getenv("KAKAO_REFRESH_TOKEN")

    if not rest_api_key or not refresh_token:
        raise ValueError(
            ".env 파일에 KAKAO_REST_API_KEY/KAKAO_REFRESH_TOKEN 값이 필요합니다. "
            "먼저 get_kakao_token.py를 실행해 토큰을 발급받아주세요."
        )

    payload = {
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "refresh_token": refresh_token,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    response = requests.post(KAKAO_TOKEN_URL, data=payload)
    response.raise_for_status()
    token_data = response.json()

    access_token = token_data.get("access_token")
    if not access_token:
        raise ValueError(f"응답에서 access_token을 찾을 수 없습니다: {token_data}")

    set_key(ENV_PATH, "KAKAO_ACCESS_TOKEN", access_token)

    new_refresh_token = token_data.get("refresh_token")
    if new_refresh_token:
        set_key(ENV_PATH, "KAKAO_REFRESH_TOKEN", new_refresh_token)

    return access_token


def build_text_template(text: str) -> dict:
    """
    카카오 "나에게 보내기" API가 요구하는 template_object(딕셔너리)를 만든다.

    - object_type="text" : 카카오 메시지 템플릿 중 가장 단순한 텍스트 전용 형식
    - text               : 카카오톡 채팅방에 실제로 표시될 메시지 본문
    - link               : 메시지를 눌렀을 때 이동할 링크 정보. API 스펙상 필수
      필드이지만, 특별히 이동시킬 페이지가 없다면 빈 문자열로 두어도
      정상적으로 전송된다.
    """
    return {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": "",
            "mobile_web_url": "",
        },
    }


def send_memo(access_token: str, template_object: dict) -> dict:
    """
    카카오 "나에게 보내기" API를 호출해 template_object 내용을 내 카카오톡으로 전송하고,
    응답 JSON을 딕셔너리로 반환한다.
    """
    # 액세스 토큰은 Authorization 헤더에 "Bearer {토큰}" 형식으로 담아 전달한다
    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    # 카카오 API는 template_object 값을 "JSON 문자열"로 직렬화해서
    # application/x-www-form-urlencoded 형식(=requests의 data= 인자)으로 보내야 한다.
    # 딕셔너리를 그대로 넘기면 안 되고 json.dumps()로 문자열 변환이 필요하다.
    # ensure_ascii=False로 두어야 한글이 깨지지 않고 그대로 직렬화된다.
    payload = {
        "template_object": json.dumps(template_object, ensure_ascii=False),
    }

    response = requests.post(KAKAO_MEMO_SEND_URL, headers=headers, data=payload)

    # 요청이 실패(4xx, 5xx)하면 예외를 발생시켜 문제를 바로 알 수 있도록 한다
    # (예: 401이면 액세스 토큰 만료, 403이면 동의항목 미설정 등)
    response.raise_for_status()

    return response.json()


def main():
    # 1. .env에서 액세스 토큰 읽기
    access_token = load_access_token()

    # 2. 전송할 텍스트 메시지 템플릿 만들기
    template_object = build_text_template(MESSAGE_TEXT)

    # 3. "나에게 보내기" API 호출
    print("[INFO] 카카오톡 '나에게 보내기' 메시지를 전송하는 중입니다...")
    result = send_memo(access_token, template_object)

    # 4. 결과 출력
    # 카카오 API는 성공 시 result_code 0을 반환한다
    if result.get("result_code") == 0:
        print("[INFO] 메시지 전송에 성공했습니다.")
    else:
        print(f"[WARN] 예상치 못한 응답을 받았습니다: {result}")


if __name__ == "__main__":
    main()
