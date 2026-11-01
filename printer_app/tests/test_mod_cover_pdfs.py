"""Contract, persistence and PDF regressions for the approved Olympia cover."""
from __future__ import annotations

from dataclasses import asdict
from io import BytesIO

from pypdf import PdfReader
import pytest

from printer_app.db import Database
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import clean_draft
from printer_app.mod_resulting.cover_report import (
    apply_edits, has_result, project_cover,
)
from printer_app.mod_resulting.cover_pdf import render_cover_pdf
from printer_app.mod_resulting.pdf_export import render_resulting_pdf
from printer_app.mod_resulting.pdf_repository import ModPdfRepository
from printer_app.mod_resulting.pdf_service import ModPdfService
from printer_app.mod_resulting.repository import ResultingRepository

DAY = "2026-10-30"


def _card(number, work_type, name, reps=(), source="Canvass"):
    return ModSheetRecord(
        source_id="0WO00000000000" + str(number) + "AAA",
        lead_source_id="00Q000000000001AAA",
        work_order_number="000023" + str(number).zfill(2),
        work_type=work_type, lead_name=name, source=source, phone="360-555-0101",
        canvass_set_by="Morgan Taylor", assigned_service_resources=tuple(reps),
        product_interest="Roofing", scheduled_start="2026.10.30 ; 10:00:00 AM"
    )


def _item(record, draft):
    return {"work_order_id": record.source_id, "snapshot": asdict(record), "draft": draft}


def _sale(price, deposit, start, *, product="Roofing"):
    return clean_draft({
        "dispo": "sale", "start_price_override": str(start),
        "sale_products": {product: {"price": str(price), "deposit": str(deposit)}},
        "docs": True,
    })


def test_work_type_is_not_sold_product_and_all_fields_follow_approved_map():
    roofing = _card(1, "Roofing", "Evelyn Carter",
                    ("James Taylor", "Sofia Reyes"))
    bath = _card(2, "Bath", "Liam West")
    gutters = _card(3, "Gutters", "Alex Shore", ("Tyler James",))
    report = project_cover(DAY, [
        _item(roofing, _sale(30000, 1200, 40000, product="Windows")),
        _item(bath, clean_draft({"dispo": "np", "cxl_at_lead": True})),
        _item(gutters, _sale(10000, 700, 20000, product="Gutters")),
    ], "Beau Baker")
    roof = report["sections"][0]
    assert roof["title"] == "Roofing Division"
    assert roof["summary"]["leads"] == "1"
    assert roof["summary"]["day_total"] == "$30,000"
    row = roof["rows"][0]
    assert row["client_name"] == "Evelyn Carter"
    assert row["marketer"] == "Morgan Taylor"
    assert row["sales_rep"] == "James / Sofia"
    assert row["product"] == "W"
    assert row["sold_at"] == "75%"
    assert row["deposit"] == "$1,200"
    assert row["doc_signing"] == "Yes"
    assert row["cash_finance"] == row["poi"] == row["manager_sign"] == ""
    assert report["sections"][4]["summary"]["day_total"] == "$10,000"
    assert report["totals"]["reps_paid"] == "3"
    assert report["totals"]["average_deposit"] == "$950"
    assert report["grand"]["leads"] == "3"
    assert report["grand"]["closing_pct"] == "67%"
    assert report["totals"]["mod"] == "Beau Baker"


def test_deposit_slash_source_only_counts_first_component():
    row = _card(4, "Siding", "Test Customer")
    draft = clean_draft({
        "dispo": "sale", "final_price_override": "22500",
        "deposit_override": "900/125", "start_price_override": "30000",
    })
    report = project_cover(DAY, [_item(row, draft)])
    output = report["sections"][2]["rows"][0]
    assert output["deposit"] == "$900"
    assert output["price"] == "$22,500"
    assert output["sold_at"] == "75%"


def test_cxl_at_lead_is_not_resulting_and_never_reclassifies_no_pitch():
    assert not has_result(clean_draft({"cxl_at_lead": True}))
    assert has_result(clean_draft({"dispo": "np", "cxl_at_lead": True}))
    report = project_cover(DAY, [
        _item(_card(1, "Bath", "Test"), clean_draft(
            {"dispo": "np", "cxl_at_lead": True}))
    ])
    assert report["totals"]["sales"] == "0"
    assert report["totals"]["nra"] == "0"
    assert report["grand"]["pitched"] == "0"


def test_every_cover_cell_and_summary_is_editable_without_losing_nra():
    sale = _card(1, "Roofing", "Customer", ("Rep One",))
    nra = _card(2, "Bath", "No Rep")
    original = project_cover(DAY, [
        _item(sale, _sale(15000, 500, 20000)),
        _item(nra, clean_draft({"dispo": "nra"}))
    ])
    changes = {
        "rows": {sale.source_id: {"client_name": "Edited Customer",
                                  "price": "$20,000", "cash_finance": "Finance",
                                  "poi": "Yes"}},
        "summary": {"roof": {"leads": "5", "pitch_pct": "19%"}},
        "grand": {"dpl": "$200"},
        "totals": {"average_sale": "$99", "mod": "Edited MOD"}
    }
    edited = apply_edits(original, changes)
    row = edited["sections"][0]["rows"][0]
    assert row["price"] == "$20,000"
    assert row["cash_finance"] == "Finance"
    assert row["poi"] == "Yes"
    assert edited["sections"][0]["summary"]["dpl"] == "$4,000"
    assert edited["sections"][0]["summary"]["pitch_pct"] == "19%"
    assert edited["grand"]["dpl"] == "$200"
    assert edited["totals"]["average_sale"] == "$99"
    assert edited["totals"]["mod"] == "Edited MOD"
    assert edited["totals"]["nra"] == "1"
    assert original["sections"][0]["rows"][0]["price"] == "$15,000"


def test_cover_pdf_matches_landscape_approved_shape_and_keeps_overflow():
    records = [
        _item(_card(i, "Roofing", "Customer " + str(i)),
              _sale(1000 + i, 100, 2000))
        for i in range(1, 9)
    ]
    report = project_cover(DAY, records)
    payload = render_cover_pdf(report)
    pages = PdfReader(BytesIO(payload)).pages
    assert len(pages) == 2
    assert (float(pages[0].mediabox.width), float(pages[0].mediabox.height)) == (
        1008, 612)
    assert "OLYMPIA" in pages[0].extract_text()
    assert "Gutters" in pages[0].extract_text()
    assert "Grand Total" in pages[0].extract_text()
    assert "Customer 8" in pages[1].extract_text()
    assert "Customer 8" not in pages[0].extract_text()


def test_durable_cover_first_queue_and_edit_while_eod_runs(tmp_path):
    db = Database(tmp_path / "printer.sqlite")
    source = ResultingRepository(db)
    cover = ModPdfRepository(db)
    first = _card(1, "Roofing", "Sold Customer", ("Rep One", "Rep Two"))
    second = _card(2, "Bath", "No Pitch")
    source.refresh(DAY, [first, second], external_drafts={
        first.source_id: _sale(15000, 500, 20000),
        second.source_id: clean_draft({})
    }, market_segment="Olympia")
    service = ModPdfService(cover, source, render_resulting_pdf,
                            tmp_path / "pdfs")
    with pytest.raises(ValueError, match="need resulting"):
        service.begin(DAY)
    source.save_draft(DAY, second.source_id,
                      clean_draft({"dispo": "np"}), 0)
    queued = service.begin(DAY)
    job_id = queued["job_id"]
    assert queued["total_sheets"] == 2
    assert cover.job(DAY, job_id)["state"] == "queued"
    assert service.process_next()["state"] == "awaiting_confirmation"
    assert (tmp_path / "pdfs" / str(job_id) / "cover.pdf").exists()
    assert (tmp_path / "pdfs" / str(job_id) / "mod.pdf").exists()
    with pytest.raises(ValueError, match="not ready"):
        service.pdf_path(DAY, job_id)

    # Report editing must not be blocked by an in-progress Salesforce batch.
    with db.connect() as conn:
        conn.execute("UPDATE mod_result_days SET submitting=1 WHERE day=?", (DAY,))
    edits = {"rows": {first.source_id: {"price": "$25,000"}}}
    assert service.confirm(DAY, job_id, edits, 0) == 1
    assert service.process_next()["state"] == "ready"
    pdf = PdfReader(str(service.pdf_path(DAY, job_id)))
    assert len(pdf.pages) == 2  # cover first, then all MOD cards (3/page)
    assert "OLYMPIA" in pdf.pages[0].extract_text()
    assert "$25,000" in pdf.pages[0].extract_text()
    assert "Sold Customer" in pdf.pages[1].extract_text()
    assert cover.edits(DAY)[0] == edits
    assert source.sheets(DAY)[0]["draft"]["sale_products"]["Roofing"]["price"] == "15000"

    with pytest.raises(ValueError, match="Reload"):
        service.confirm(DAY, job_id, {}, 0)
    assert service.confirm(DAY, job_id, {"grand": {"dpl": "$42"}}, 1) == 2
    assert cover.job(DAY, job_id)["state"] == "pending_finalize"
    assert service.process_next()["state"] == "ready"
    text = PdfReader(str(service.pdf_path(DAY, job_id))).pages[0].extract_text()
    assert "$42" in text
    assert source.sheets(DAY)[0]["draft"]["sale_products"]["Roofing"]["price"] == "15000"


def test_cover_normalizer_and_renderer_remain_replaceable():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "mod_resulting"
    for module in ("cover_report.py", "cover_pdf.py"):
        code = (root / module).read_text()
        tree = ast.parse(code)
        imports = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        ]
        # The cover projection and PDF drawing must remain pure and cannot
        # acquire Salesforce, SQLite, Flask, worker, or file-system adapters.
        forbidden = ("salesforce", "sqlite", "flask", "repository", "worker")
        assert not any(any(part in name.lower() for part in forbidden)
                       for name in imports)
    service = (root / "pdf_service.py").read_text()
    service_tree = ast.parse(service)
    service_imports = [
        alias.name for node in ast.walk(service_tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    ]
    assert not any("salesforce" in name.lower() or "sqlite" in name.lower()
                   for name in service_imports)
