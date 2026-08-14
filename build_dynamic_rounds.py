"""trade_log.csv를 종목별 매매 라운드로 쪼개고, 그 결과를 매매일지 엑셀의
"롤링 서식" 블록(라운드 하나 = 17행 안팎의 반복 블록)으로 그려주는 로직.

update_trading_journal.py가 이 모듈의 build_rounds()/rebuild_sheet()를 불러 쓴다.
"""

import copy
from datetime import datetime

BUY_CODE = "2"  # watch_trades.py의 check_once()와 동일한 관례: sell_tp=="2"면 매수, 그 외는 매도

MIN_DETAIL_ROWS = 8  # 라운드 하나당 매수/매도 각각 기본으로 확보하는 입력 행 수
FIRST_HEADER_ROW = 5
BLOCK_GAP_ROWS = 3  # 합계 행 다음, 다음 블록 헤더 전까지 비워두는 여백 행 수

LABEL_ROW_TEXT = {
    "C": "손익액", "E": "수익률", "F": "매수평단가", "G": "매수수량", "H": "매수금액",
    "I": "매도평단가", "J": "매도수량", "K": "매도금액", "L": "제세금합계",
    "M": "매수수수료", "N": "매도수수료+세금", "O": "비고",
    "S": "25년 증권거래세 0.15%",
}
SUBHEADER_ROW_TEXT = {
    "E": "매수", "I": "손익분기단가", "J": "잔여주식수량", "K": "매도",
    "O": "증권거래세+매도수수료",
}
COLHEADER_ROW_TEXT = {
    "E": "날짜", "F": "매수단가", "G": "수량", "H": "합계",
    "K": "날짜", "L": "매도단가", "M": "수랑", "N": "합계", "O": "매수수수료",
}
SELL_FEE_RATE = 0.00165  # h+3행 P열 (증권거래세+매도수수료율)
BUY_FEE_RATE = 0.00015   # h+4행 P열 (매수수수료율)


# ---------------------------------------------------------------------------
# 1. 라운드 분리 로직
# ---------------------------------------------------------------------------

def _to_number(value, cast):
    if value in (None, ""):
        return 0
    try:
        return cast(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0


def _parse_date(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def split_stock_rows_into_rounds(rows):
    """한 종목의 체결 행들(원본 CSV 순서 그대로)을 라운드 단위로 쪼갠다.

    라운드는 보유수량이 0에서 시작해 매수로 커졌다가 다시 0으로 돌아올 때까지의
    구간이다. 파일이 끝났는데 수량이 0이 아니면(진행 중인 라운드) 그대로 포함한다.
    """
    rounds = []
    current = None
    position = 0

    for row in rows:
        is_buy = str(row.get("매수매도", "")) == BUY_CODE
        qty = _to_number(row.get("체결수량"), int)
        price = _to_number(row.get("체결가"), float)
        fill = {
            "is_buy": is_buy,
            "date": _parse_date(row.get("날짜")),
            "price": price,
            "qty": qty,
            "csv_index": row["_csv_index"],
        }

        if current is None:
            current = {"종목명": row.get("종목명", ""), "fills": [], "in_progress": False}
        current["fills"].append(fill)

        position += qty if is_buy else -qty
        if position <= 0:
            current["in_progress"] = False
            rounds.append(current)
            current = None
            position = 0

    if current is not None:
        current["in_progress"] = True
        rounds.append(current)

    return rounds


def _moving_average_buy_price(fills):
    """체결 순서 그대로 이동평균법을 적용해 매입가 평단가를 계산한다.

    매수 시: 평균단가 = (기존평균×기존수량 + 신규단가×신규수량) / (기존+신규수량)
    매도 시: 수량만 줄고 평균단가는 그대로 유지.
    """
    avg = 0.0
    qty = 0
    for fill in fills:
        if fill["is_buy"]:
            new_qty = qty + fill["qty"]
            if new_qty > 0:
                avg = (avg * qty + fill["price"] * fill["qty"]) / new_qty
            qty = new_qty
        else:
            qty -= fill["qty"]
    return avg


def build_rounds(csv_rows):
    """계좌 전체 체결 행(원본 CSV 순서)을 받아, 여러 종목의 라운드를 실제 발생
    순서에 가깝게 하나의 시퀀스로 합쳐서 반환한다.

    csv_rows: csv.DictReader로 읽은 dict 리스트 (원본 파일 순서 유지).
    """
    by_stock = {}
    for idx, row in enumerate(csv_rows):
        row = dict(row)
        row["_csv_index"] = idx
        by_stock.setdefault(row.get("종목명", ""), []).append(row)

    all_rounds = []
    for stock_rows in by_stock.values():
        all_rounds.extend(split_stock_rows_into_rounds(stock_rows))

    all_rounds.sort(key=lambda r: r["fills"][0]["csv_index"])
    return all_rounds


# ---------------------------------------------------------------------------
# 2. 블록 스타일 캡처 (지우기 전에, 기존 서식을 본떠온다)
# ---------------------------------------------------------------------------

def capture_block_style(ws, sample_header_row=FIRST_HEADER_ROW):
    h = sample_header_row
    detail_row = h + 5

    def cell_style(coord):
        c = ws[coord]
        return {
            "font": copy.copy(c.font),
            "border": copy.copy(c.border),
            "fill": copy.copy(c.fill),
            "alignment": copy.copy(c.alignment),
            "number_format": c.number_format,
        }

    style = {
        "label": {col: cell_style(f"{col}{h}") for col in "CEFGHIJKLMNO"},
        "label_S": cell_style(f"S{h}"),
        "summary": {col: cell_style(f"{col}{h + 1}") for col in "CEFGHIJKLMN"},
        "subheader": {col: cell_style(f"{col}{h + 3}") for col in "EIJKO"},
        "subheader_P": cell_style(f"P{h + 3}"),
        "colheader": {col: cell_style(f"{col}{h + 4}") for col in "EFGHIJKLMNO"},
        "colheader_P": cell_style(f"P{h + 4}"),
        "detail": {col: cell_style(f"{col}{detail_row}") for col in "CEFGHKLMN"},
        "totals": {col: cell_style(f"{col}{h + 13}") for col in "FGHILMN"},
    }
    return style


def _apply_style(cell, style):
    cell.font = style["font"]
    cell.border = style["border"]
    cell.fill = style["fill"]
    cell.alignment = style["alignment"]
    cell.number_format = style["number_format"]


# ---------------------------------------------------------------------------
# 3. 시트 지우기 / 블록 작성
# ---------------------------------------------------------------------------

def clear_rounds_area(ws, from_row=FIRST_HEADER_ROW):
    """from_row(기본 5행)부터 시트 끝까지 값/서식/병합을 모두 지운다.

    1~4행(제목, 계좌명, 누적손익합계, 세율 범례)은 건드리지 않는다.
    """
    for merged_range in list(ws.merged_cells.ranges):
        if merged_range.min_row >= from_row:
            ws.unmerge_cells(str(merged_range))

    max_row = max(ws.max_row, from_row)
    max_col = max(ws.max_column, 19)  # S열까지
    for row in ws.iter_rows(min_row=from_row, max_row=max_row, max_col=max_col):
        for cell in row:
            cell.value = None


def write_round_block(ws, header_row, round_data, style):
    """헤더 행이 header_row인 라운드 블록 하나를 그린다. 다음 블록이 시작할
    헤더 행 번호를 반환한다."""
    buys = [f for f in round_data["fills"] if f["is_buy"]]
    sells = [f for f in round_data["fills"] if not f["is_buy"]]
    detail_rows = max(MIN_DETAIL_ROWS, len(buys), len(sells))

    h = header_row
    colheader_row = h + 4
    detail_start = h + 5
    totals_row = detail_start + detail_rows

    # h+0: 라벨 행
    for col, text in LABEL_ROW_TEXT.items():
        if col == "S":
            continue
        cell = ws[f"{col}{h}"]
        cell.value = text
        _apply_style(cell, style["label"][col])
    s_cell = ws[f"S{h}"]
    s_cell.value = LABEL_ROW_TEXT["S"]
    _apply_style(s_cell, style["label_S"])

    # h+1: 라운드 요약 수식 행
    summary_formulas = {
        "C": f"=K{h + 1}-H{h + 1}-L{h + 1}",
        "E": f"=IFERROR(C{h + 1}/(H{h + 1}+L{h + 1}),0)",
        "F": f"=IFERROR(F{totals_row},0)",
        "G": f"=G{totals_row}",
        "H": f"=H{totals_row}",
        "I": f"=IFERROR(L{totals_row},0)",
        "J": f"=M{totals_row}",
        "K": f"=N{totals_row}",
        "L": f"=M{h + 1}+N{h + 1}",
        "M": f"=H{h + 1}*P{h + 4}",
        "N": f"=K{h + 1}*P{h + 3}",
    }
    for col, formula in summary_formulas.items():
        cell = ws[f"{col}{h + 1}"]
        cell.value = formula
        _apply_style(cell, style["summary"][col])

    # h+3: 매수/매도 서브헤더
    for col, text in SUBHEADER_ROW_TEXT.items():
        cell = ws[f"{col}{h + 3}"]
        cell.value = text
        _apply_style(cell, style["subheader"][col])
    p_sell_fee = ws[f"P{h + 3}"]
    p_sell_fee.value = SELL_FEE_RATE
    _apply_style(p_sell_fee, style["subheader_P"])

    # h+4: 컬럼 헤더 + 손익분기단가/잔여주식수량 수식
    for col, text in COLHEADER_ROW_TEXT.items():
        cell = ws[f"{col}{colheader_row}"]
        cell.value = text
        _apply_style(cell, style["colheader"][col])
    ws[f"I{colheader_row}"].value = (
        f"=IFERROR((((H{h + 1}+M{h + 1}-K{h + 1})/J{colheader_row})"
        f"+((H{h + 1}*P{h + 3})/J{colheader_row}+1)),0)"
    )
    _apply_style(ws[f"I{colheader_row}"], style["colheader"]["I"])
    ws[f"J{colheader_row}"].value = f"=G{totals_row}-M{totals_row}"
    _apply_style(ws[f"J{colheader_row}"], style["colheader"]["J"])
    p_buy_fee = ws[f"P{colheader_row}"]
    p_buy_fee.value = BUY_FEE_RATE
    _apply_style(p_buy_fee, style["colheader_P"])

    # 종목명 (C열, detail 구간 전체 병합)
    ws.merge_cells(f"C{detail_start}:C{totals_row}")
    name_cell = ws[f"C{detail_start}"]
    name_cell.value = round_data["종목명"]
    _apply_style(name_cell, style["detail"]["C"])

    # 매수/매도 서브헤더 라벨 병합 (E:H = 매수, K:N = 매도)
    ws.merge_cells(f"E{h + 3}:H{h + 3}")
    ws.merge_cells(f"K{h + 3}:N{h + 3}")

    # detail_rows개의 체결 입력 행
    for i in range(detail_rows):
        r = detail_start + i
        for col in "EFGHKLMN":
            _apply_style(ws[f"{col}{r}"], style["detail"][col])

        ws[f"H{r}"].value = f"=F{r}*G{r}"
        ws[f"N{r}"].value = f"=L{r}*M{r}"

        if i < len(buys):
            fill = buys[i]
            ws[f"E{r}"].value = fill["date"]
            ws[f"F{r}"].value = fill["price"]
            ws[f"G{r}"].value = fill["qty"]
        if i < len(sells):
            fill = sells[i]
            ws[f"K{r}"].value = fill["date"]
            ws[f"L{r}"].value = fill["price"]
            ws[f"M{r}"].value = fill["qty"]

    # 합계 행
    totals_formulas = {
        "F": f"=IFERROR((H{totals_row}/G{totals_row}),0)",
        "G": f"=SUM(G{colheader_row}:G{totals_row - 1})",
        "H": f"=SUM(H{colheader_row}:H{totals_row - 1})",
        "I": f"=N{totals_row}-H{totals_row}",
        "L": f"=IFERROR((N{totals_row}/M{totals_row}),0)",
        "M": f"=SUM(M{colheader_row}:M{totals_row - 1})",
        "N": f"=SUM(N{colheader_row}:N{totals_row - 1})",
    }
    for col, formula in totals_formulas.items():
        cell = ws[f"{col}{totals_row}"]
        cell.value = formula
        _apply_style(cell, style["totals"][col])

    # 진행중(미완결) 라운드는 매수평단가를 단순평균이 아니라 이동평균법으로 덮어쓴다.
    if round_data.get("in_progress"):
        f_cell = ws[f"F{totals_row}"]
        f_cell.value = _moving_average_buy_price(round_data["fills"])
        _apply_style(f_cell, style["totals"]["F"])

    return totals_row + 1 + BLOCK_GAP_ROWS


def rebuild_sheet(ws, rounds):
    """시트를 완전히 지우고, rounds(=build_rounds()의 결과)를 처음부터 다시 그린다."""
    style = capture_block_style(ws)
    clear_rounds_area(ws)

    header_row = FIRST_HEADER_ROW
    for round_data in rounds:
        header_row = write_round_block(ws, header_row, round_data, style)

    last_row = max(header_row - 1, FIRST_HEADER_ROW)
    ws["H3"] = f"=SUM(C{FIRST_HEADER_ROW}:C{last_row})"
