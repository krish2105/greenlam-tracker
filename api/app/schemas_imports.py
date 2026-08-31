"""Wire shapes for the Excel register import.

Deliberately verbose about what WOULD happen. The whole safety property of this
feature is that the person uploading sees the consequences before agreeing to
them, and a response that says only `{"ok": true, "rows": 3841}` gives them
nothing to check against.
"""

from datetime import date, datetime

from pydantic import BaseModel


class RowIssueRead(BaseModel):
    row: int
    column: str
    message: str
    severity: str  # error | warning


class PlannedRowRead(BaseModel):
    row: int
    action: str  # create | update | skip
    machine_code: str
    date: date
    minutes: int
    description: str
    reason: str | None = None


class ImportPlanRead(BaseModel):
    file_hash: str
    sheet_name: str
    rows_read: int
    creates: int
    updates: int
    skips: int
    errors: int
    can_commit: bool
    missing_columns: list[str]
    unknown_machines: list[str]
    issues: list[RowIssueRead]
    # The totals accompany the capped lists so the UI can say "showing 60 of
    # 912" rather than implying it is showing everything.
    issues_total: int
    sample: list[PlannedRowRead]
    sample_total: int


class ImportRunRead(BaseModel):
    id: int
    filename: str
    status: str
    rows_read: int
    created_count: int
    updated_count: int
    skipped_count: int
    error_count: int
    uploaded_by: str
    created_at: datetime
