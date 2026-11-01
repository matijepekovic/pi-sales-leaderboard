"""Workflow owner for Redlines PDFs and the independently editable OLY cover."""
from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .cover_pdf import render_cover_pdf
from .calc_pdf import render_calc_pdf
from .calc_report import project_calc, apply_calc_edits
from .cover_report import apply_edits, has_result, project_cover


class ModPdfService:
    def __init__(self, repository, resulting_repository, mod_pdf_renderer, output_dir,
                 color_code=lambda: False):
        self.repository = repository
        self.resulting_repository = resulting_repository
        self.mod_pdf_renderer = mod_pdf_renderer
        self.output_dir = Path(output_dir)
        self.color_code = color_code

    def begin(self, day):
        sheets = self.resulting_repository.print_sheets(day)
        if not sheets:
            raise ValueError("There are no MOD sheets for this day.")
        incomplete = [item["snapshot"].get("work_order_number") or item["work_order_id"]
                      for item in sheets if not has_result(item["draft"])]
        if incomplete:
            raise ValueError(
                str(len(incomplete)) + " MOD sheet(s) still need resulting: " +
                ", ".join(str(value) for value in incomplete[:5]))
        state = self.resulting_repository.day(day) or {}
        base = project_cover(day, sheets, state.get("mod_user_name") or "")
        edits, _ = self.repository.edits(day)
        apply_edits(base, edits)  # Validate stored edits before queuing.
        base_calc = project_calc(day, sheets)
        calc_edits, _ = self.repository.calc_edits(day)
        apply_calc_edits(base_calc, calc_edits)
        job_id = self.repository.enqueue(
            day, base, sheets, edits, self.color_code(),
            base_calc=base_calc, calc_edits=calc_edits)
        return {"job_id": job_id, "total_sheets": len(sheets)}

    def editor(self, day, job_id):
        job = self.repository.job(day, job_id)
        return {
            "job_id": job_id,
            "day": day,
            "revision": job["revision"],
            "report": apply_edits(job["base_cover"], job["edits"]),
            "edits": job["edits"],
            "state": job["state"],
            "confirmed": bool(job["confirmed"]),
        }

    def calc_editor(self, day, job_id):
        job = self.repository.job(day, job_id)
        if job["calc_state"] == "unavailable":
            raise LookupError("OLY Calc is unavailable for this PDF job.")
        return {
            "job_id": job_id, "day": day, "revision": job["calc_revision"],
            "report": apply_calc_edits(job["calc_base"], job["calc_edits"]),
            "edits": job["calc_edits"], "state": job["calc_state"],
            "confirmed": bool(job["calc_confirmed"]),
        }

    def confirm_calc(self, day, job_id, edits, revision):
        job = self.repository.job(day, job_id)
        apply_calc_edits(job["calc_base"], edits)
        return self.repository.confirm_calc(day, job_id, edits, revision)

    def calc_status(self, day, job_id):
        job = self.repository.job(day, job_id)
        return {
            "job_id": job_id, "state": job["calc_state"],
            "confirmed": bool(job["calc_confirmed"]),
            "ready": job["calc_state"] == "ready", "error": job["calc_error"],
        }

    def calc_pdf_path(self, day, job_id):
        job = self.repository.job(day, job_id)
        if job["calc_state"] != "ready" or not job["calc_confirmed"]:
            raise ValueError("OLY Calc is not ready. Confirm it and check progress.")
        path = self._job_dir(job_id) / "OLY Calc.pdf"
        if not path.is_file():
            raise ValueError("OLY Calc PDF file is missing.")
        return path

    def confirm(self, day, job_id, edits, revision):
        job = self.repository.job(day, job_id)
        apply_edits(job["base_cover"], edits)  # Validate all user-owned cells.
        return self.repository.confirm(day, job_id, edits, revision)

    def status(self, day, job_id):
        job = self.repository.job(day, job_id)
        return {
            "job_id": job["id"], "state": job["state"],
            "stage": job["stage"], "confirmed": bool(job["confirmed"]),
            "ready": job["state"] == "ready",
            "error": job["error"],
        }

    def pdf_path(self, day, job_id):
        job = self.repository.job(day, job_id)
        if job["state"] != "ready" or not job["confirmed"]:
            raise ValueError("Redlines PDF is not ready. Confirm the cover and check progress.")
        path = self._job_dir(job_id) / "Redlines.pdf"
        if not path.is_file():
            raise ValueError("Redlines PDF file is missing.")
        return path

    def _job_dir(self, job_id):
        return self.output_dir / str(int(job_id))

    def _write(self, job_id, filename, payload):
        directory = self._job_dir(job_id)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = directory / (filename + ".tmp")
        path = directory / filename
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        return path

    def _finalize(self, job_id):
        """Read current saved edits immediately before publishing the final PDF."""
        job = self.repository.job_any(job_id)
        report = apply_edits(job["base_cover"], job["edits"])
        final_cover = render_cover_pdf(report)
        cover = self._write(job_id, "cover.pdf", final_cover)
        mod = self._job_dir(job_id) / "mod.pdf"
        if not mod.is_file():
            raise ValueError("MOD-sheet PDF is unavailable for finalization.")
        result = PdfWriter()
        for path in (cover, mod):
            with path.open("rb") as handle:
                pdf = PdfReader(handle)
                for page in pdf.pages:
                    result.add_page(page)
        buffer = BytesIO()
        result.write(buffer)
        self._write(job_id, "Redlines.pdf", buffer.getvalue())
        return self.repository.mark_ready(job_id, job["revision"])

    def _finalize_calc(self, job_id):
        """Capture the latest confirmed Calc edits and publish its own PDF."""
        job = self.repository.job_any(job_id)
        report = apply_calc_edits(job["calc_base"], job["calc_edits"])
        self._write(job_id, "OLY Calc.pdf", render_calc_pdf(report))
        return self.repository.mark_calc_ready(job_id, job["calc_revision"])

    def process_next(self):
        """Worker-only. Never waits on the cover editor or submits Salesforce."""
        claimed = self.repository.claim()
        if claimed is None:
            return None
        job_id = claimed["id"]
        if claimed["kind"] == "calc":
            try:
                if claimed["state"] == "rendering":
                    report = apply_calc_edits(claimed["calc_base"], claimed["calc_edits"])
                    self._write(job_id, "calc_draft.pdf", render_calc_pdf(report))
                    if not self.repository.finished_calc_render(job_id):
                        return {"job_id": job_id, "state": "awaiting_confirmation", "kind": "calc"}
                    if self.repository.begin_calc_finalize(job_id) is None:
                        return {"job_id": job_id, "state": "awaiting_confirmation", "kind": "calc"}
                ready = self._finalize_calc(job_id)
                return {"job_id": job_id,
                        "state": "ready" if ready else "pending_finalize",
                        "kind": "calc"}
            except Exception as exc:
                self.repository.fail_calc(job_id, str(exc))
                raise
        try:
            if claimed["state"] == "rendering":
                report = apply_edits(claimed["base_cover"], claimed["edits"])
                self._write(job_id, "cover.pdf", render_cover_pdf(report))
                self.repository.progress(job_id, "mod_sheets")
                self._write(job_id, "mod.pdf", self.mod_pdf_renderer(
                    claimed["sheets"], color_code=bool(claimed["color_code"])))
                if not self.repository.finished_render(job_id):
                    return {"job_id": job_id, "state": "awaiting_confirmation"}
                final = self.repository.begin_finalize(job_id)
                if final is None:
                    return {"job_id": job_id, "state": "awaiting_confirmation"}
            ready = self._finalize(job_id)
            return {"job_id": job_id, "state": "ready" if ready else "pending_finalize"}
        except Exception as exc:
            self.repository.fail(job_id, str(exc))
            raise
