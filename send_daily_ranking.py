"""
오늘 만든 3가지 키움 순위 조회 결과
(실시간종목조회순위 / 거래대금상위 / 시가총액상위)를 카테고리별로 별도의
카카오톡 "나에게 보내기" 메시지로 순차 전송하는 스크립트.

재사용 원칙:
- 코드를 새로 베껴 쓰지 않고, 이미 만들어둔 스크립트를 파이썬 모듈로 import해서
  그 안의 함수를 그대로 호출하는 방식으로 재사용한다.
  - 실시간종목조회순위(ka00198)/거래대금상위(ka10032) 조회: get_kiwoom_ranking.py
  - 시가총액상위(ka10099 기반) 조회: get_kiwoom_marketcap_ranking.py
  - 카카오톡 "나에게 보내기" 전송: send_kakao_message.py
- 세 스크립트 모두 `if __name__ == "__main__":` 가드로 감싸져 있어서,
  import만 해서는 자동으로 실행되지 않고 함수만 가져다 쓸 수 있다.

전체 흐름:
1. get_kiwoom_ranking.load_app_credentials()/issue_access_token()으로
   키움 접근토큰을 "한 번만" 발급받는다. (조회순위/거래대금/시가총액 조회 3번 모두
   이 토큰 하나를 공용으로 사용 - 매번 새로 발급받을 필요가 없다)
2. get_kiwoom_ranking.request_ranking()을 두 번 호출해
   실시간종목조회순위(ka00198), 거래대금상위(ka10032)를 각각 조회하고,
   ETF/ETN·우선주를 제외한 뒤 상위 TOP_N개만 추린다.
   (ka00198은 ka10030/ka10032와 달리 거래량/거래대금이 아니라 "실시간 조회 빈도"
    기준 순위이며, 등락률에 해당하는 필드명도 flu_rt가 아니라 base_comp_chgr다.
    get_kiwoom_ranking.request_ranking()이 TR_ID에 따라 요청 URL/payload를
    알아서 분기하므로 이 스크립트에서는 TR_ID만 바꿔주면 된다.)
3. get_kiwoom_marketcap_ranking.request_stock_list()로 KOSPI+KOSDAQ 전체
   종목을 모은 뒤, 같은 방식으로 ETF/ETN·우선주를 제외하고 시가총액
   (상장주식수 x 현재가) 기준으로 정렬해 상위 TOP_N개를 추린다.
4. 세 리스트를 각각 "카테고리 제목 + 순위 / 종목명 / 등락률" 위주의
   별도 텍스트로 정리한다.
   (단, 시가총액상위는 ka10099 응답에 등락률 필드가 없어 대신 시가총액(억원)을 보여준다.
    이는 이전 대화에서 확인한 ka10099 API 자체의 한계다.)
5. send_kakao_message.load_access_token()/build_text_template()/send_memo()를
   그대로 호출해 카테고리별 메시지를 전송 전 글자 수를 출력하며 순차적으로
   카카오톡으로 전송한다.
"""

import sys

# 아래 세 모듈은 오늘 이미 만들어둔 스크립트를 그대로 import해서 재사용한다.
# (모듈 이름 그대로 쓰면 매번 "get_kiwoom_ranking.xxx"처럼 길어지므로 별칭을 붙인다)
import get_kiwoom_ranking as ranking
import get_kiwoom_marketcap_ranking as marketcap
import send_kakao_message as kakao

# Windows 콘솔(cp949) 환경에서 한글/이모지 출력 시 오류가 나는 것을 방지
sys.stdout.reconfigure(encoding="utf-8")

# 각 순위 항목별로 몇 개씩 뽑아 보여줄지
TOP_N = 20


def fetch_inquiry_and_value_top5(token: str) -> dict:
    """
    실시간종목조회순위(ka00198)와 거래대금상위(ka10032)를 조회해 각각 상위 TOP_N개를 돌려준다.

    get_kiwoom_ranking.request_ranking() 함수는 자기 모듈의 전역 변수인
    ranking.TR_ID 값을 읽어서 어떤 TR을 호출할지 결정하도록 만들어져 있다.
    (get_kiwoom_ranking.py를 "python get_kiwoom_ranking.py ka10032"처럼
    커맨드라인 인자로 실행하던 방식과 동일한 동작을 함수 재사용으로 흉내내는 것)
    그래서 여기서는 호출 직전에 ranking.TR_ID 값을 바꿔가며 두 번 호출한다.
    """
    results = {}

    for tr_id in ("ka00198", "ka10032"):
        ranking.TR_ID = tr_id  # request_ranking()이 내부적으로 참조하는 TR 코드를 전환

        tr_name = ranking.TR_NAMES.get(tr_id, "")
        print(f"[INFO] {tr_id}({tr_name}) 조회 중...")
        data = ranking.request_ranking(token)

        # 응답 JSON에서 실제 순위 리스트가 들어있는 키를 찾는다.
        # TR마다 키 이름이 달라서(tdy_trde_qty_upper, trde_prica_upper 등)
        # "리스트 타입이면서 비어있지 않은 값"을 가진 첫 번째 키를 사용한다.
        list_key = next(
            (k for k, v in data.items() if isinstance(v, list) and v),
            None,
        )
        if not list_key:
            print(f"[WARN] {tr_id} 응답에서 리스트 데이터를 찾지 못했습니다: {data}")
            results[tr_id] = []
            continue

        # ETF/ETN, 우선주 제외 (get_kiwoom_ranking.is_common_stock 재사용)
        filtered = [
            item for item in data[list_key]
            if ranking.is_common_stock(item.get("stk_nm", ""))
        ]
        results[tr_id] = filtered[:TOP_N]

    return results


def fetch_marketcap_top5(token: str) -> list:
    """
    KOSPI(mrkt_tp=0)+ KOSDAQ(mrkt_tp=10) 전체 종목을 모아 시가총액 상위 TOP_N개를 돌려준다.

    get_kiwoom_marketcap_ranking.py와 마찬가지로, ka10099는 "순위 조회 TR"이
    아니라 시장별 전체 종목 목록을 주는 TR이기 때문에 직접 시가총액을 계산해서
    정렬해야 한다.
    """
    all_items = []
    for mrkt_tp, label in marketcap.MARKETS.items():
        print(f"[INFO] ka10099(종목정보 리스트) {label}(mrkt_tp={mrkt_tp}) 조회 중...")
        all_items.extend(marketcap.request_stock_list(token, mrkt_tp))

    # ETF/ETN/리츠, 우선주 제외 (get_kiwoom_marketcap_ranking.is_common_stock 재사용)
    common = [item for item in all_items if marketcap.is_common_stock(item)]

    # 시가총액 = 상장주식수(listCount) x 현재가(lastPrice)
    for item in common:
        item["market_cap"] = int(item["listCount"]) * int(item["lastPrice"])

    ranked = sorted(common, key=lambda x: x["market_cap"], reverse=True)
    return ranked[:TOP_N]


# 카카오 "나에게 보내기" 텍스트 메시지의 안전한 길이 기준(글자 수)
MAX_MESSAGE_LENGTH = 200


def build_inquiry_message(inquiry_top: list) -> str:
    """
    실시간종목조회순위(ka00198) 리스트를 "[실시간종목조회순위 TOP{TOP_N}]" 제목의
    메시지 본문으로 정리한다.

    ka00198 응답에는 ka10030/ka10032와 달리 flu_rt(등락률) 필드가 없고, 대신
    base_comp_chgr(기준가 대비 등락율, 부호 포함 %)가 온다.
    """
    lines = [f"[실시간종목조회순위 TOP{TOP_N}]"]
    for i, item in enumerate(inquiry_top, start=1):
        lines.append(f"{i}. {item.get('stk_nm', '')} ({item.get('base_comp_chgr', '')}%)")
    return "\n".join(lines)


def format_rank_change(item: dict) -> str:
    """
    ka10032 응답의 now_rank(현재순위)/pred_rank(전일순위)로 전일 대비 순위 변동을 계산한다.

    ka10032에는 ka00198의 rank_chg처럼 변동값을 바로 주는 필드가 없어서 직접 뺄셈으로 구한다.
    순위가 올랐으면(숫자가 작아졌으면) ▲n, 내렸으면 ▼n, 그대로면 '-'.
    """
    try:
        diff = int(item.get("pred_rank")) - int(item.get("now_rank"))
    except (TypeError, ValueError):
        return "-"

    if diff > 0:
        return f"▲{diff}"
    if diff < 0:
        return f"▼{-diff}"
    return "-"


def build_value_message(value_top: list) -> str:
    """거래대금상위(ka10032) 리스트를 "[거래대금상위 TOP{TOP_N}]" 제목의 메시지 본문으로 정리한다."""
    lines = [f"[거래대금상위 TOP{TOP_N}]"]
    for i, item in enumerate(value_top, start=1):
        rank_change = format_rank_change(item)
        lines.append(f"{i}. {item.get('stk_nm', '')} ({item.get('flu_rt', '')}%) [{rank_change}]")
    return "\n".join(lines)


def build_marketcap_message(marketcap_top: list) -> str:
    """
    시가총액상위(ka10099 기반) 리스트를 "[시가총액상위 TOP{TOP_N}]" 제목의 메시지 본문으로 정리한다.

    ka10099 응답에는 등락률 필드가 없어서, 대신 계산한 시가총액을 억원 단위로 보여준다
    (name 필드, market_cap은 fetch_marketcap_top5에서 계산해둠).
    """
    lines = [f"[시가총액상위 TOP{TOP_N}]"]
    for i, item in enumerate(marketcap_top, start=1):
        cap_eok = item["market_cap"] // 100_000_000
        lines.append(f"{i}. {item.get('name', '')} ({cap_eok:,}억원)")
    return "\n".join(lines)


def send_category_message(kakao_token: str, title: str, message_text: str) -> None:
    """
    카테고리 하나의 메시지 본문을 글자 수와 함께 출력하고, 카카오톡으로 전송한다.

    카카오 "나에게 보내기" 텍스트 템플릿은 너무 긴 메시지를 보내면 실패할 수 있어서,
    전송 전에 글자 수를 출력해 MAX_MESSAGE_LENGTH(200자) 이내인지 눈으로 확인할 수 있게 한다.
    """
    length = len(message_text)
    status = "OK" if length <= MAX_MESSAGE_LENGTH else "WARN: 200자 초과"
    print(f"[INFO] {title} 메시지 길이: {length}자 ({status})")

    print(f"----- {title} 전송할 메시지 미리보기 -----")
    print(message_text)
    print("----------------------------------\n")

    template_object = kakao.build_text_template(message_text)
    print(f"[INFO] {title} 메시지를 카카오톡 '나에게 보내기'로 전송하는 중입니다...")
    result = kakao.send_memo(kakao_token, template_object)

    if result.get("result_code") == 0:
        print(f"[INFO] {title} 메시지 전송에 성공했습니다.")
    else:
        print(f"[WARN] {title} 메시지 전송 중 예상치 못한 응답을 받았습니다: {result}")


def main():
    # 1. 키움 접근토큰을 한 번만 발급받아 세 번의 조회에 공용으로 사용한다
    app_key, secret_key = ranking.load_app_credentials()
    token = ranking.issue_access_token(app_key, secret_key)

    # 2. 실시간종목조회순위/거래대금상위 조회
    vv = fetch_inquiry_and_value_top5(token)

    # 3. 시가총액상위 조회
    mc_top5 = fetch_marketcap_top5(token)

    # 4. 카테고리별로 메시지 본문을 따로 정리한다 (하나로 합치지 않는다)
    inquiry_message = build_inquiry_message(vv["ka00198"])
    value_message = build_value_message(vv["ka10032"])
    marketcap_message = build_marketcap_message(mc_top5)

    # 5. send_kakao_message.py의 전송 기능을 재사용해 카테고리별로 순차 전송한다
    kakao_token = kakao.load_access_token()

    send_category_message(kakao_token, "실시간종목조회순위", inquiry_message)
    send_category_message(kakao_token, "거래대금상위", value_message)
    send_category_message(kakao_token, "시가총액상위", marketcap_message)


if __name__ == "__main__":
    main()
