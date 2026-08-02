"""
삼성전자(005930) 최근 5년치 일봉 데이터를 수집하여 CSV로 저장하는 스크립트
"""

import os
from datetime import datetime, timedelta

import FinanceDataReader as fdr


# 조회할 종목 코드 (삼성전자)
STOCK_CODE = "005930"

# 조회할 기간(일 단위). 5년 = 365일 * 5
LOOKBACK_DAYS = 365 * 5

# 저장할 CSV 파일 경로
OUTPUT_DIR = "data"
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "samsung.csv")


def get_date_range():
    """
    오늘 날짜를 기준으로 최근 5년(LOOKBACK_DAYS일)에 해당하는
    시작일과 종료일 문자열(YYYY-MM-DD)을 반환한다.
    """
    end_date = datetime.today()
    start_date = end_date - timedelta(days=LOOKBACK_DAYS)

    # FinanceDataReader는 'YYYY-MM-DD' 형식의 문자열을 인자로 받는다
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def fetch_samsung_data(start_date: str, end_date: str):
    """
    FinanceDataReader를 이용해 삼성전자의 일봉 시세 데이터를 가져온다.

    반환되는 DataFrame은 기본적으로 다음 컬럼을 포함한다:
    - Open  : 시가
    - High  : 고가
    - Low   : 저가
    - Close : 종가
    - Volume: 거래량
    - Change: 전일 대비 등락률

    인덱스는 거래일(Date, datetime 형식)이다.
    """
    df = fdr.DataReader(STOCK_CODE, start_date, end_date)
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


def main():
    start_date, end_date = get_date_range()

    print(f"[INFO] 삼성전자({STOCK_CODE}) 일봉 데이터 조회 기간: {start_date} ~ {end_date}")

    # 1. 데이터 수집
    df = fetch_samsung_data(start_date, end_date)
    print(f"[INFO] 수집된 데이터 행 수: {len(df)}")

    # 2. CSV 파일로 저장
    save_to_csv(df, OUTPUT_PATH)
    print(f"[INFO] 데이터 저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
