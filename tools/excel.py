"""
Excel tools.

- generate_table: LLM produces headers/rows dynamically (never hard-coded).
- excel_create_table: writes those headers/rows into a workbook via
  openpyxl. This is the reliable, headless path and is used by default.
- excel_control_live: optional pywin32-based path that drives an already
  open Excel instance directly, for when the user wants to see it happen
  live rather than just save a file.
"""
from __future__ import annotations

import os
import platform
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from agent.llm import LLM
from agent.prompts import TABLE_GENERATION_SYSTEM
from config import Config
from utils.logger import heartbeat

_IS_WINDOWS = platform.system() == "Windows"


def _resolve_save_path(save_path: str, default_name: str = "output.xlsx") -> Path:
    """
    Make whatever the LLM (or user) supplied into an actually-usable file path.

    Handles the failure modes seen in practice:
    - Literal unresolved placeholders like "C:\\Users\\username\\Documents\\"
      (the LLM guessed a path instead of using the real machine's username).
    - A bare directory (trailing slash, no filename) instead of a file path.
    - A relative/blank path.
    - Missing ".xlsx" extension.
    - Parent directory that doesn't exist yet.
    """
    raw = (save_path or "").strip()

    # Expand ~, %ENV% vars, etc.
    raw = os.path.expandvars(os.path.expanduser(raw)) if raw else ""

    path = Path(raw) if raw else Path(default_name)

    # Replace an unresolved literal "username" segment with the real user.
    real_user = Path.home().name
    parts = [real_user if p.lower() == "username" else p for p in path.parts]
    path = Path(*parts) if parts else path

    # If it's a directory (trailing separator, or an existing directory,
    # or has no filename component at all) append the default filename.
    if raw.endswith(("\\", "/")) or path.is_dir() or path.name == "":
        path = path / default_name

    # Ensure it ends in .xlsx.
    if path.suffix.lower() != ".xlsx":
        path = path.with_name(path.name + ".xlsx")

    # If the parent directory doesn't exist (e.g. a guessed path), fall
    # back to the real Documents folder rather than failing outright.
    if not path.parent.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            path = Config.HOME / "Documents" / path.name
            path.parent.mkdir(parents=True, exist_ok=True)

    return path


def generate_table(topic: str, row_count: int = 10, llm: LLM | None = None) -> dict:
    llm = llm or LLM()
    prompt = f"Create a table about: {topic}. Include {row_count} rows of realistic dummy data."
    try:
        with heartbeat("Generating table data"):
            data = llm.chat_json(TABLE_GENERATION_SYSTEM, prompt)
        headers = data.get("headers")
        rows = data.get("rows")
        if not headers or not rows:
            return {"success": False, "error": "LLM did not return headers/rows"}
        return {"success": True, "headers": headers, "rows": rows}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"Table generation failed: {exc}"}


def excel_create_table(
    headers: list,
    rows: list,
    save_path: str = "output.xlsx",
    sheet_name: str = "Sheet1",
    open_after_save: bool = True,
) -> dict:
    """
    Write headers/rows into a new .xlsx via openpyxl (headless, reliable),
    then — by default — actually open the saved file so it's visible in
    Excel. Without this, `open_app("excel")` just opens a blank Book1 that
    has nothing to do with the file this function writes, which looks like
    "nothing happened" even though the data was saved correctly.
    """
    try:
        if not isinstance(headers, list) or not isinstance(rows, list):
            return {
                "success": False,
                "error": (
                    "headers/rows were not resolved to real data before reaching "
                    "excel_create_table (still a placeholder or wrong type). "
                    "This indicates a planner/executor bug, not a data problem — "
                    "please retry the command."
                ),
            }

        resolved_path = _resolve_save_path(save_path)

        wb = Workbook()
        ws = wb.active
        ws.title = sheet_name

        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")

        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill

        for row_idx, row in enumerate(rows, start=2):
            for col_idx, value in enumerate(row, start=1):
                ws.cell(row=row_idx, column=col_idx, value=value)

        for col_idx, header in enumerate(headers, start=1):
            col_letter = get_column_letter(col_idx)
            longest = max([len(str(header))] + [len(str(r[col_idx - 1])) for r in rows if col_idx - 1 < len(r)])
            ws.column_dimensions[col_letter].width = longest + 4

        wb.save(resolved_path)

        opened = False
        open_error = None
        if open_after_save and _IS_WINDOWS:
            try:
                import os as _os
                _os.startfile(str(resolved_path))  # hands off to Excel via the shell
                opened = True
            except Exception as exc:  # noqa: BLE001 - file is still saved even if this fails
                open_error = str(exc)

        message = f"Workbook saved to {resolved_path}"
        if opened:
            message += " and opened in Excel"
        elif open_after_save and open_error:
            message += f" (could not auto-open it: {open_error} — open it manually)"

        return {
            "success": True,
            "message": message,
            "path": str(resolved_path),
            "opened": opened,
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"Failed to create workbook: {exc}"}


def excel_append_rows(path: str, rows: list, sheet_name: str | None = None) -> dict:
    try:
        wb = load_workbook(path)
        ws = wb[sheet_name] if sheet_name else wb.active
        for row in rows:
            ws.append(row)
        wb.save(path)
        return {"success": True, "message": f"Appended {len(rows)} row(s) to {path}"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"Failed to append rows: {exc}"}


def excel_control_live(headers: list, rows: list) -> dict:
    """Drive an already-running Excel instance directly via pywin32 (COM),
    for when the user wants to watch the table being built live."""
    if not _IS_WINDOWS:
        return {"success": False, "error": "excel_control_live requires Windows (pywin32)."}
    try:
        import win32com.client  # local import: Windows-only dependency

        excel_app = win32com.client.Dispatch("Excel.Application")
        excel_app.Visible = True
        workbook = excel_app.Workbooks.Add()
        sheet = workbook.ActiveSheet

        for col_idx, header in enumerate(headers, start=1):
            sheet.Cells(1, col_idx).Value = header
        for row_idx, row in enumerate(rows, start=2):
            for col_idx, value in enumerate(row, start=1):
                sheet.Cells(row_idx, col_idx).Value = value

        return {"success": True, "message": "Live Excel table created"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"Live Excel control failed: {exc}"}
