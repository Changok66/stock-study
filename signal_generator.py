"""
SOXL "43/-43+Up/Down 구름 예약매수 + G역전 비중축소 + ATR(20,x3) 트레일링스탑"
최종 확정 전략(세션정리_지표검증및전략확정_20260820.md의 9-6절)의 매수/매도/손절 신호를
매일 감지해 카카오톡으로 "알림만" 보내는 1단계(신호 알림) 스크립트.
아직 실제 주문은 넣지 않는다 - 자동주문(2/3단계)은 이 알림 단계를 최소 2주 이상
검증한 뒤 별도로 진행한다.

흐름:
1. get_data.py의 FDR 조회 함수(fetch_fdr_ohlcv/save_to_csv)를 그대로 재사용해
   SOXL 최신 데이터로 data/price_SOXL.csv를 갱신한다(상장일부터 전체기간을 매번
   다시 받는다 - 4천여 행뿐이라 매일 통째로 받아도 비용이 크지 않고, 코드도 단순해진다).
2. backtest_soxl_reserved.prepare_data()/simulate_reserved_strategy()로 지표를
   계산하고 최종 확정 전략(reduce_on_g_inversion=True, atr_multiplier=3)을 전체
   히스토리에 대해 다시 실행해 diagnostics_df(일별 비중/트리거/실효여부)를 얻는다.
   매일 처음부터 다시 시뮬레이션하는 방식이라 별도의 "현재 포지션 상태" 파일을 따로
   관리할 필요가 없다 - 과거 신호는 이미 확정된 값들이라 몇 번을 다시 계산해도
   항상 같은 결과가 나온다(멱등성).
3. diagnostics_df의 가장 최근 행(=방금 갱신한 데이터의 마지막 날, 즉 최근 미국장
   마감일)에 트리거가 있으면 카카오톡 "나에게 보내기"로 알림을 보낸다
   (send_daily_ranking.py처럼 send_kakao_message.refresh_access_token()으로 매번
   토큰을 갱신한 뒤 전송). 트리거가 없으면 카카오톡은 보내지 않는다.
4. 트리거가 있었던 날은(실제 체결 효과가 없는 경우 포함) data/signal_vs_actual_log.csv에
   누적 기록한다 - 날짜/종가/트리거/방향/예약비중변화/실효있음/신호 당시 비중을 자동
   기록하고, "실제판단"/"비고" 두 칸은 공란으로 남겨 사용자가 나중에 직접 채워 넣게
   한다(최소 2주 이상 매일 받아보면서 실제 판단과 신호를 비교하는 것이 이 로그의 목적).

Windows 작업 스케줄러 등록: send_daily_ranking.py/daily_ranking_task.xml과 같은 패턴으로
soxl_signal_task.xml + register_soxl_signal_task.bat를 함께 만들었다.
사용법은 register_soxl_signal_task.bat 참고(평일 07:30 KST 실행 - 미국 정규장 마감
06:00 KST(서머타임 기준, 표준시는 07:00) 이후로 넉넉히 잡았다).
"""

import csv
import os
import sys

import pandas as pd

import backtest_soxl_reserved as bsr
import get_data
import send_kakao_message as kakao

# Windows 콘솔(cp949) 환경에서 한글 출력 시 오류가 나는 것을 방지
sys.stdout.reconfigure(encoding="utf-8")

SOXL_PRICE_PATH = "data/price_SOXL.csv"
SOXL_START_DATE = "2010-03-11"  # SOXL 상장일

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "signal_vs_actual_log.csv")
LOG_HEADER = [
    "날짜", "종가", "트리거", "방향", "예약비중변화(%p)", "실효있음", "신호당시비중(%)",
    "실제판단", "비고",
]

# 세션정리 9-6절에서 확정한 최종 전략 파라미터
STRATEGY_KWARGS = {"reduce_on_g_inversion": True, "atr_multiplier": 3}


def refresh_soxl_data() -> None:
    """get_data.py의 FDR 조회 함수를 그대로 재사용해 SOXL 데이터를 최신으로 갱신한다."""
    start_date, end_date = get_data.get_date_range(SOXL_START_DATE)
    print(f"[INFO] SOXL 데이터 갱신 중(FDR): {start_date} ~ {end_date}")
    df = get_data.fetch_fdr_ohlcv("SOXL", start_date, end_date)
    get_data.save_to_csv(df, SOXL_PRICE_PATH)
    print(f"[INFO] {SOXL_PRICE_PATH} 갱신 완료 (최근 거래일: {df.index.max().date()}, {len(df)}행)")


def direction_label(trigger: str) -> str:
    """트리거 문자열에서 매수/매도/손절 방향을 사람이 보기 쉬운 라벨로 뽑는다."""
    is_buy = "매수" in trigger
    is_sell = "매도" in trigger or "축소" in trigger
    is_stop = "손절" in trigger or "청산" in trigger
    if is_stop:
        return "손절/청산"
    if is_buy and is_sell:
        return "매수+매도(동시)"
    if is_buy:
        return "매수"
    if is_sell:
        return "매도/축소"
    return "기타"


def build_message(row: pd.Series) -> str:
    """카카오톡 알림 본문을 만든다."""
    date_str = row["Date"].strftime("%Y-%m-%d")
    direction = direction_label(row["트리거"])
    lines = [
        f"[SOXL 신호 알림] {date_str} 종가 기준",
        f"방향: {direction}",
        f"트리거: {row['트리거']}",
        f"종가: {row['Close']:.2f}",
        f"현재 비중(이 신호 반영 전): {row['비중'] * 100:.1f}%",
        f"예약된 비중변화: {row['예약비중변화'] * 100:+.1f}%p (다음 거래일 시가 체결 예정)",
    ]
    if not row["실효있음"]:
        lines.append("※ 참고: 이미 목표 비중 근처라 실제로는 체결 효과가 거의/전혀 없을 수 있습니다.")
    lines.append("※ 알림 단계입니다 - 자동주문은 아직 실행되지 않았습니다. 직접 판단 후 매매하세요.")
    return "\n".join(lines)


def send_kakao_notification(message: str) -> None:
    try:
        access_token = kakao.refresh_access_token()
    except Exception as exc:
        print(f"[WARN] 카카오 토큰 갱신 실패({exc}), .env에 남아있는 기존 토큰으로 시도합니다.")
        access_token = kakao.load_access_token()

    try:
        result = kakao.send_memo(access_token, kakao.build_text_template(message))
        if result.get("result_code") == 0:
            print("[INFO] 카카오톡 알림 전송 완료")
        else:
            print(f"[WARN] 카카오톡 전송 응답이 예상과 다릅니다: {result}")
    except Exception as exc:
        print(f"[WARN] 카카오톡 전송 실패: {exc}")


def append_signal_log(row: pd.Series) -> None:
    """신호 발생 내역을 data/signal_vs_actual_log.csv에 이어서(append) 기록한다."""
    log_dir = os.path.dirname(LOG_PATH)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    file_exists = os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(LOG_HEADER)
        writer.writerow([
            row["Date"].strftime("%Y-%m-%d"),
            round(row["Close"], 2),
            row["트리거"],
            direction_label(row["트리거"]),
            round(row["예약비중변화"] * 100, 2),
            row["실효있음"],
            round(row["비중"] * 100, 2),
            "",  # 실제판단 - 사용자가 직접 채워 넣는 칸
            "",  # 비고 - 사용자가 직접 채워 넣는 칸
        ])


def main():
    refresh_soxl_data()

    df = bsr.prepare_data()  # 방금 갱신한 data/price_SOXL.csv를 다시 읽어 지표를 계산한다
    _, _, diagnostics_df = bsr.simulate_reserved_strategy(df, **STRATEGY_KWARGS)

    latest = diagnostics_df.iloc[-1]
    print(f"[INFO] 최신 거래일: {latest['Date'].date()}, 종가: {latest['Close']:.2f}, "
          f"현재 비중: {latest['비중'] * 100:.1f}%")

    if pd.isna(latest["트리거"]) or not latest["트리거"]:
        print("[INFO] 오늘 트리거된 신호가 없습니다. 카카오톡 알림을 보내지 않습니다.")
        return

    print(f"[INFO] 트리거 감지: {latest['트리거']} (실효있음={latest['실효있음']})")

    message = build_message(latest)
    send_kakao_notification(message)

    append_signal_log(latest)
    print(f"[INFO] {LOG_PATH}에 신호 기록 완료")


if __name__ == "__main__":
    main()
