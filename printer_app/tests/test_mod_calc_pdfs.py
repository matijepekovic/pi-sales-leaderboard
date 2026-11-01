"""OLY Calc mapping, approved PDF layout, and independent report-job tests."""
from __future__ import annotations

from dataclasses import asdict
from io import BytesIO

from pypdf import PdfReader
import pytest

from printer_app.db import Database
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.calc_report import (
    apply_calc_edits, project_calc,
)
from printer_app.mod_resulting.calc_pdf import render_calc_pdf
from printer_app.mod_resulting.contract import clean_draft
from printer_app.mod_resulting.pdf_export import render_resulting_pdf
from printer_app.mod_resulting.pdf_repository import ModPdfRepository
from printer_app.mod_resulting.pdf_service import ModPdfService
from printer_app.mod_resulting.repository import ResultingRepository

DAY = "2026-10-30"


def card(index, draft, *, work_type="Roofing"):
    record = ModSheetRecord(
        source_id="0WO" + str(index).zfill(12) + "AAA",
        lead_source_id="00Q000000000001AAA",
        work_order_number=str(2550000 + index),
        lead_name="Customer " + str(index), work_type=work_type,
        product_interest="Roofing",
        assigned_service_resources=("Alex North",),
    )
    return {"work_order_id": record.source_id,
            "snapshot": asdict(record), "draft": draft}


def entry(dispo, **extra):
    return clean_draft({"dispo": dispo, **extra})


def sale(price):
    return entry("sale", sale_products={
        "Roofing": {"price": str(price), "deposit": "500"}})


def sample_cards():
    prices = (30000, 40000, 25000, 50000, 38475)
    result = [card(i, sale(price)) for i, price in enumerate(prices, 1)]
    result += [card(i, entry("pns")) for i in range(6, 13)]
    result += [card(i, entry("np", result_detail="Not Home"))
               for i in range(13, 15)]
    result += [card(i, entry("np")) for i in range(15, 18)]
    result += [card(18, entry("nra"))]
    result += [card(i, entry("cxl")) for i in range(19, 21)]
    result += [card(21, entry("oos"))]
    return result


def test_matches_approved_preview_and_original_oly_calc_formulas():
    report = project_calc(DAY, sample_cards())
    assert report["work_orders"] == 21
    assert report["oos"] == 1
    assert report["inputs"] == {
        "sold": "5", "pns": "7", "nh": "2", "np": "3",
        "nra": "1", "cxl": "2", "revenue": "$183,475.00",
    }
    assert report["outputs"] == {
        "leads": "18", "pitch": "66.7%", "pitch_nra": "70.6%",
        "close": "27.8%", "close_nra": "29.4%",
        "total": "$183,475.00", "dpl": "$10,193.06", "nra_total": "1",
    }


def test_cxl_at_lead_is_not_cxl_and_multiple_products_count_one_sale():
    multi = entry("sale", sale_products={
        "Roofing": {"price": "15000", "deposit": "700"},
        "Windows": {"price": "9000", "deposit": "100"},
    }, cxl_at_lead=True)
    other = entry("np", result_detail="Not Home", cxl_at_lead=True)
    report = project_calc(DAY, [
        card(1, multi), card(2, other), card(3, entry("cxl")),
        card(4, entry("oos")),
    ])
    assert report["inputs"]["sold"] == "1"
    assert report["inputs"]["nh"] == "1"
    assert report["inputs"]["cxl"] == "1"
    assert report["inputs"]["revenue"] == "$24,000.00"
    assert report["outputs"]["leads"] == "2"
    assert report["outputs"]["close"] == "50.0%"


def test_secondary_sale_counts_one_sold_work_order_not_pns_or_two_products():
    mixed = entry("pns", additional_products=True,
                  product_results={
                      "Roofing": {"result": "pns", "detail": "", "price": "", "deposit": ""},
                      "Windows": {"result": "sale", "detail": "", "price": "12000",
                                  "deposit": "0"},
                  })
    report = project_calc(DAY, [card(1, mixed)])
    assert report["inputs"]["sold"] == "1"
    assert report["inputs"]["pns"] == "0"
    assert report["outputs"]["leads"] == "1"
    assert report["inputs"]["revenue"] == "$12,000.00"


def test_user_edits_recalculate_and_can_override_every_output():
    original = project_calc(DAY, sample_cards())
    edited = apply_calc_edits(original, {
        "inputs": {"cxl": "3", "revenue": "$200000"},
        "outputs": {"pitch": "80%", "leads": "100"},
    })
    assert edited["outputs"]["leads"] == "100"
    assert edited["outputs"]["pitch"] == "80%"
    assert edited["outputs"]["close"] == "5.0%"  # Edited Leads now drives Close.
    assert edited["outputs"]["dpl"] == "$2,000.00"
    assert edited["outputs"]["total"] == "$200,000.00"
    derived = apply_calc_edits(original, {"inputs":{"cxl":"3","revenue":"$200000"}})
    assert derived["outputs"]["leads"] == "17"
    assert derived["outputs"]["close"] == "29.4%"
    assert derived["outputs"]["dpl"] == "$11,764.71"
    total_override = apply_calc_edits(original, {"outputs":{"total":"$300,000.00"}})
    assert total_override["outputs"]["dpl"] == "$16,666.67"
    assert original["outputs"]["leads"] == "18"
    zero = apply_calc_edits(original, {
        "inputs": {"sold": "0", "pns": "0", "nh": "0", "np": "0", "nra": "0"}
    })
    assert zero["outputs"]["pitch"] == ""
    assert zero["outputs"]["pitch_nra"] == ""


def test_pdf_contains_compact_oly_calc_and_embedded_original_artwork():
    report = project_calc(DAY, sample_cards())
    pdf = PdfReader(BytesIO(render_calc_pdf(report)))
    assert len(pdf.pages) == 1
    page = pdf.pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == (720, 650)
    text = page.extract_text()
    for expected in ("Olympia, WA", "#1 in Puget Sound", "MOD Results",
                     "Total Sale Rev", "$183,475.00", "$10,193.06",
                     "CXL and OOS excluded"):
        assert expected in text
    assert len(page.images) >= 1


def test_calc_confirmation_and_redlines_are_separate_durable_jobs(tmp_path):
    db = Database(tmp_path / "printer.sqlite")
    resulting = ResultingRepository(db)
    cards = sample_cards()
    records = [ModSheetRecord(**dict(
        item["snapshot"],
        assigned_service_resources=tuple(
            item["snapshot"]["assigned_service_resources"])
    )) for item in cards]
    resulting.refresh(
        DAY, records,
        external_drafts={row["work_order_id"]:row["draft"] for row in cards},
        market_segment="Olympia")
    repo = ModPdfRepository(db)
    service = ModPdfService(repo, resulting, render_resulting_pdf, tmp_path / "pdf")
    job_id = service.begin(DAY)["job_id"]
    assert service.calc_status(DAY, job_id)["state"] == "queued"
    assert service.process_next()["state"] == "awaiting_confirmation"
    assert not service.status(DAY, job_id)["confirmed"]
    calc = service.process_next()
    assert calc == {"job_id":job_id, "state":"awaiting_confirmation", "kind":"calc"}
    with pytest.raises(ValueError, match="not ready"):
        service.calc_pdf_path(DAY, job_id)

    # Cover remains unconfirmed; Calc can confirm while EOD holds the day.
    with db.connect() as conn:
        conn.execute("UPDATE mod_result_days SET submitting=1 WHERE day=?", (DAY,))
    edits = {"inputs":{"revenue":"$199999"}, "outputs":{"pitch":"75%"}}
    assert service.confirm_calc(DAY, job_id, edits, 0) == 1
    assert service.process_next()["state"] == "ready"
    assert service.calc_status(DAY, job_id)["ready"]
    assert not service.status(DAY, job_id)["ready"]
    pdf = PdfReader(str(service.calc_pdf_path(DAY, job_id)))
    assert "$199,999.00" in pdf.pages[0].extract_text()
    assert "75%" in pdf.pages[0].extract_text()
    unchanged = resulting.print_sheets(DAY)
    assert len(unchanged) == 21
    assert unchanged[0]["draft"]["sale_products"]["Roofing"]["price"] == "30000"
    assert unchanged[18]["draft"]["dispo"] == "cxl"
    assert repo.calc_edits(DAY)[0] == edits

    # Re-confirming Calc invalidates only the Calc PDF.
    assert service.confirm_calc(DAY, job_id, {"inputs":{"sold":"8"}}, 1) == 2
    assert not service.calc_status(DAY, job_id)["ready"]
    assert service.process_next()["state"] == "ready"
    with pytest.raises(ValueError, match="changed"):
        service.confirm_calc(DAY, job_id, {}, 0)
    assert service.confirm(DAY, job_id, {}, 0) == 1
    assert service.process_next()["state"] == "ready"
    assert service.status(DAY, job_id)["ready"]
    assert service.calc_status(DAY, job_id)["ready"]

    # New PDF jobs reuse just the confirmed, report-only Calc edits.
    new_job = service.begin(DAY)["job_id"]
    assert service.calc_editor(DAY, new_job)["report"]["inputs"]["sold"] == "8"


def test_calc_and_cover_data_are_platform_neutral():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "mod_resulting"
    for name in ("calc_report.py", "calc_pdf.py", "report_facts.py"):
        tree = ast.parse((root / name).read_text())
        names = [
            item.name for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for item in node.names
        ]
        assert not any(any(key in value.lower() for key in
                       ("salesforce", "sqlite", "flask", "repository", "worker"))
                       for value in names)
