import os
import sys
import csv
import json
import time
import requests
from datetime import datetime, time as dtime
from dotenv import load_dotenv, set_key

import send_kakao_message as kakao

load_dotenv()
ENV_PATH = ".env"

APP_KEY = os.getenv("KIWOOM_APP_KEY")
SECRET_KEY = os.getenv("KIWOOM_SECRET_KEY")
ACCESS_TOKEN = os.getenv("KIWOOM_ACCESS_TOKEN")
KAKAO_ACCESS_TOKEN = os.getenv("KAKAO_ACCESS_TOKEN")

BASE_URL = "https://api.kiwoom.com"
KAKAO_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

SEEN_FILE = "data/seen_trade_ids.json"
LOG_FILE = "data/trade_log.csv"


def is_market_hours(now):
    if now.weekday() >= 5:
        return False
    return dtime(9, 0) <= now.time() <= dtime(15, 30)


def get_today_executions():
    url = f"{BASE_URL}/api/dostk/acnt"
    headers = {
        "content-type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "api-id": "kt00007",
    }
    today = datetime.now().strftime("%Y%m%d")
    payload = {
        "ord_dt": today,
        "qry_tp": "1",
        "stk_bond_tp": "0",
        "sell_tp": "0",
        "dmst_stex_tp": "%",
    }
    resp = requests.post(url, headers=headers, json=payload)
    data = resp.json()
    if resp.status_code != 200:
        print("[FAIL] 키움 API 오류:", resp.status_code, json.dumps(data, ensure_ascii=False)[:500])
        return []
    print("[DEBUG] 원본 응답 일부:", json.dumps(data, ensure_ascii=False, indent=2)[:1500])
    for key in ("acnt_ord_cntr_prps_dtl", "output", "list", "data"):
        if key in data and isinstance(data[key], list):
            return data[key]
    return []


def send_kakao(text, access_token):
    # access_token은 check_once()가 매번 kakao.refresh_access_token()으로 새로 발급받아
    # 넘겨준다. 여기서 예외가 나도(네트워크 오류 등) 잡아서 로그만 남기고 넘어가야, 체결
    # 하나의 전송 실패가 나머지 체결 처리(append_log/save_seen_ids)까지 막지 않는다.
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        template = {
            "object_type": "text",
            "text": text,
            "link": {"web_url": "https://www.kiwoom.com", "mobile_web_url": "https://www.kiwoom.com"},
        }
        resp = requests.post(KAKAO_MEMO_URL, headers=headers,
                              data={"template_object": json.dumps(template, ensure_ascii=False)})
        if resp.status_code != 200:
            print("[FAIL] 카카오톡 전송 실패:", resp.status_code, resp.text[:300])
        else:
            print("[OK] 카카오톡 전송 완료")
    except Exception as e:
        print(f"[FAIL] 카카오톡 전송 중 오류가 발생했습니다. 다음 체결 처리는 계속 진행합니다: {e}")


def load_seen_ids():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen_ids(ids):
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(ids), f, ensure_ascii=False)


def append_log(executions):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    file_exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["체결시각", "종목명", "매수매도", "체결가", "체결수량", "체결번호"])
        for e in executions:
            writer.writerow([
                e.get("cntr_tm", ""), e.get("stk_nm", ""), e.get("sell_tp", ""),
                e.get("cntr_pric", ""), e.get("cntr_qty", ""), e.get("ord_no", ""),
            ])


def check_once():
    if not is_market_hours(datetime.now()):
        print("[INFO] 장 운영시간이 아니라 건너뜁니다.")
        return

    executions = get_today_executions()
    if not executions:
        print("[INFO] 오늘 체결내역이 없거나 조회 실패")
        return

    seen = load_seen_ids()
    new_ones = [e for e in executions if e.get("ord_no") and e["ord_no"] not in seen]

    if not new_ones:
        print("[INFO] 새로운 체결 없음")
        return

    # 보낼 체결이 있을 때만 카카오 액세스 토큰을 새로 갱신한다 (--loop로 몇 시간씩 도는
    # 경우가 많아, 매 체크마다 무조건 갱신해두면 KAKAO_ACCESS_TOKEN이 밤새/장시간 실행 중
    # 만료돼 조용히 실패하는 일이 없어진다). 갱신이 실패해도 예외를 잡아 기존 토큰으로
    # 대체하고, 실제 전송 실패는 send_kakao()가 알아서 로그만 남기고 넘어간다.
    try:
        kakao_access_token = kakao.refresh_access_token()
    except Exception as e:
        print(f"[WARN] 카카오 액세스 토큰 갱신 실패, 기존 토큰으로 계속 진행합니다: {e}")
        kakao_access_token = KAKAO_ACCESS_TOKEN

    for e in new_ones:
        side = "매수" if str(e.get("sell_tp", "")) in ("2", "매수") else "매도"
        msg = (
            f"[체결 알림]\n"
            f"{e.get('stk_nm','')} {side}\n"
            f"체결가 {e.get('cntr_pric','')}원 x {e.get('cntr_qty','')}주\n"
            f"시각: {e.get('cntr_tm','')}"
        )
        send_kakao(msg, kakao_access_token)
        seen.add(e["ord_no"])

    append_log(new_ones)
    save_seen_ids(seen)
    print(f"[완료] 새 체결 {len(new_ones)}건 처리")


def main():
    if not (APP_KEY and SECRET_KEY and ACCESS_TOKEN and KAKAO_ACCESS_TOKEN):
        print("[FAIL] .env에 키움/카카오 인증정보가 모두 필요합니다.")
        sys.exit(1)

    if "--loop" in sys.argv:
        idx = sys.argv.index("--loop")
        minutes = int(sys.argv[idx + 1])
        print(f"[INFO] {minutes}분 간격으로 반복 체크 시작 (Ctrl+C로 종료)")
        while True:
            check_once()
            time.sleep(minutes * 60)
    else:
        check_once()


if __name__ == "__main__":
    main()
