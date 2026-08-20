# 키움 REST API — 미국주식 매수/매도 주문 (ust20000 / ust20001)

2026-08-20 세션에서 openapi.kiwoom.com 공식 GitHub 레포
(`Kiwoom-Securities/Kiwoom-REST-API`)의 `examples/미국주식/주문/` 예제 코드를 직접
확인해 정리했다. **이 문서는 정보 확인/문서화만이고, 아직 이 프로젝트 코드에는
반영하지 않았다** — SOXL 자동매매 2/3단계(자동주문)에서 실제로 쓸 때 참고한다.

## 출처

- GitHub: https://github.com/Kiwoom-Securities/Kiwoom-REST-API
- 매수 예제: `examples/미국주식/주문/buy_overseas_stock.py`
- 매도 예제: `examples/미국주식/주문/sell_overseas_stock.py`
- (참고로 같은 폴더에 `cancel_overseas_stock_order.py`(취소),
  `modify_overseas_stock_order.py`(정정), `get_overseas_orderable_quantity.py`
  (주문가능금액 조회)도 있음 - 필요하면 나중에 확인)

공식 웹 가이드(`openapi.kiwoom.com/m/guide/apiguide?jobTp=FS_JOB_TP&jobTpCode=35`)에는
TR명("미국주식 매수 주문 ust20000" 등)만 나오고 상세 파라미터 명세는 없었다 -
GitHub 예제 코드가 훨씬 구체적이라 이쪽을 기준으로 삼았다.

## 공통 사항

| 항목 | 값 |
|---|---|
| 엔드포인트 경로 | `/api/us/ordr` (매수/매도 공통 - `api-id`로 구분) |
| Base URL(추정) | `https://api.kiwoom.com` (이 프로젝트의 `get_kiwoom_ranking.BASE_URL`과 동일한 도메인일 것으로 추정 - **모의투자 서버 주소가 다를 수 있으니 실제 연동 전 재확인 필요**, GitHub 예제는 자체 `kiwoom` SDK 클라이언트로 호스트를 감춰서 문자열로 직접 확인하지는 못했다) |
| HTTP 메서드 | POST (이 프로젝트의 다른 TR 호출과 동일 - `get_kiwoom_ranking.py`의 `request_ranking()` 패턴) |
| 인증 헤더 | `authorization: Bearer {접근토큰}` (이 프로젝트 기존 패턴과 동일할 것으로 추정) |
| `api-id` 헤더 | 매수: `ust20000`, 매도: `ust20001` |
| 연속조회 | `cont_yn`/`next_key`(GitHub 예제 기준. 이 프로젝트의 기존 코드는 `cont-yn`/`next-key`처럼 하이픈을 쓰는데, 실제 REST 헤더 표기는 재확인 필요 - GitHub 예제는 SDK가 감싸고 있어 헤더의 정확한 키 표기(밑줄 vs 하이픈)를 코드만으로는 100% 확신할 수 없음) |

## 1. 미국주식 매수 주문 — `ust20000`

### 요청 바디 파라미터

| 필드명 | 설명 | 필수 | 비고 |
|---|---|---|---|
| `stex_tp` | 거래소구분 | 필수 | `NA`=AMEX, `ND`=NASDAQ, `NY`=NYSE (SOXL은 NYSE Arca 상장이라 실제 값은 실전 테스트로 확인 필요 - 이 세 값 중 어디에 해당하는지 문서에 명시 안 됨) |
| `stk_cd` | 종목코드 | 필수 | 예: `NVDA`, SOXL이면 `SOXL` |
| `ord_qty` | 주문수량 | 필수 | 문자열로 전달(예: `"10"`) |
| `trde_tp` | 해외매매구분(주문유형) | 필수 | `00`=지정가, `03`=시장가, `26`=VWAP지정가, `27`=TWAP지정가, `30`=LOC, `36`=VWAP시장가, `37`=TWAP시장가 |
| `ord_uv` | 주문단가 | 조건부 필수 | `trde_tp`가 `00`(지정가)/`30`(LOC) 등 지정가 계열이면 필수, 시장가 계열이면 빈 값 |

### 응답 필드(주요)

| 필드명 | 설명 |
|---|---|
| `return_code`/`return_msg` | 응답코드/응답메시지 |
| `stk_nm` | 종목명 |
| `ord_no` | 주문번호 |
| `fc_entra` | 외화예수금 |
| `tdy_rebuy_useda` | 금일재매수사용금액 |
| `pred_rebuy_useda` | 전일재매수사용금액 |
| `trst_prof_ch` | 사용증거금 |

## 2. 미국주식 매도 주문 — `ust20001`

### 요청 바디 파라미터

| 필드명 | 설명 | 필수 | 비고 |
|---|---|---|---|
| `stk_cd` | 종목코드 | 필수 | |
| `stex_tp` | 거래소구분 | 필수 | `NA`/`ND`/`NY` (매수와 동일) |
| `ord_qty` | 주문수량 | 필수 | |
| `trde_tp` | 매매구분(주문유형) | 필수 | 매수의 7개 값에 `33`=MOC, `34`=STOP LIMIT, `35`=STOP이 추가된 9개: `00` 지정가, `03` 시장가, `26` VWAP지정가, `27` TWAP지정가, `30` LOC, `33` MOC, `34` STOP LIMIT, `35` STOP, `36` VWAP시장가, `37` TWAP시장가 |
| `ord_uv` | 주문단가 | 조건부 필수 | 지정가 계열이면 필수, 시장가 계열이면 빈 값 |
| `stop_pric` | STOP가격 | 조건부 필수 | `trde_tp`가 `34`(STOP LIMIT) 또는 `35`(STOP)일 때만 필수, 그 외엔 무시/빈값 |

### 응답 필드(주요)

| 필드명 | 설명 |
|---|---|
| `return_code`/`return_msg` | 응답코드/응답메시지 |
| `stk_nm` | 종목명 |
| `ord_no` | 주문번호 |
| `poss_qty` | 보유수량 |
| `tdy_resel_usedq` | 금일재매도사용수량 |
| `pred_resel_usedq` | 전일재매도사용수량 |

## 이 프로젝트의 최종 확정 전략(9-6절)에 적용할 때 참고할 점

- 전략의 매수/매도는 전부 **다음 거래일 시가 체결** 가정인데, `trde_tp=00`(지정가)로
  당일 시가 근처 가격을 직접 지정해 넣거나, `trde_tp=03`(시장가)으로 그냥 시가
  근접 체결을 노리는 두 가지 방식이 가능해 보인다 - 어느 쪽이 백테스트 가정과
  더 가까운지는 실제 연동 시 결정해야 한다.
- ATR 트레일링스탑("전량 손절")은 `stop_pric`을 쓰는 `trde_tp=34/35`(STOP/STOP
  LIMIT) 주문유형과 개념적으로 맞닿아 있다 - 자동주문 단계에서는 매일 계산한
  스탑 가격을 이 필드에 넣는 방식도 검토할 만하다(현재 전략은 "종가 확정 후 다음날
  시가 손절"이라 이 프로젝트 방식과는 다르지만, 더 정교하게 가면 실시간 STOP
  주문으로 바꿀 수도 있다는 뜻).
- `ord_qty`가 정수 주식수 필요 - 지금 백테스트는 비중(%)으로 시뮬레이션하므로,
  실제 주문 시점에 계좌 잔고/현재가 기준으로 정수 주식수로 환산하는 절차가 필요하다
  (세션정리 9-7절에 이미 적어둔 미해결 사항).
- 이 문서의 "비고" 칸에 적어둔 불확실한 부분(base URL, `stex_tp`가 SOXL에 맞는 값이
  무엇인지, 헤더 키 표기)은 실제 계좌로 테스트하기 전에 반드시 재확인해야 한다 -
  지금은 코드 작성 없이 정보만 확인한 단계다.
