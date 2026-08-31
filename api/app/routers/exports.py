"""Serving the nightly workbook to the dashboard.

THIS ENDPOINT NEVER BUILDS ANYTHING

It reads a file that a scheduled job already wrote, and that separation is a
hard architectural rule rather than a preference. Render's free tier is 512 MB
and 0.1 CPU; openpyxl assembling a workbook from a few thousand rows would take
the instance down, and it would do so at the exact moment somebody senior
clicked a button. Generation lives on the GitHub Actions runner, which has the
memory and no user waiting on it.

So the worst thing that can happen here is a 404 saying the workbook has not
been built yet — which is a true and actionable statement, unlike a timeout.

WHY THE STATUS ENDPOINT EXISTS SEPARATELY

The button needs to know the file's age before anyone clicks it. A dashboard
that silently hands you a workbook built nine days ago is worse than one that
says "last built nine days ago" and lets you decide.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from ..config import get_settings
from ..deps import CanViewDashboard
from ..schemas_exports import ExportStatusRead

router = APIRouter(prefix="/exports", tags=["exports"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _latest() -> Path | None:
    """The canonical workbook, if the job has produced one.

    The export writes ONE file and overwrites it, so this is a glob of a
    directory that should contain exactly one workbook. `max` by mtime is a
    cheap guard against a leftover from before that change, or an archive copy
    someone dropped in by hand — always serve the newest rather than whichever
    the filesystem happened to list first.
    """
    directory = Path(get_settings().export_dir)
    if not directory.is_dir():
        return None
    candidates = [
        p
        for p in directory.glob("*.xlsx")
        # Skip the atomic-write staging file, which exists for milliseconds
        # during a rebuild and is a truncated workbook while it does.
        if not p.name.startswith(".")
    ]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


@router.get("/status", response_model=ExportStatusRead, summary="Is there a workbook, and how old")
def status_(principal: CanViewDashboard) -> ExportStatusRead:
    settings = get_settings()
    path = _latest()
    if path is None:
        return ExportStatusRead(available=False, stale=False)

    stat = path.stat()
    built = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    age = datetime.now(UTC) - built
    return ExportStatusRead(
        available=True,
        filename=path.name,
        built_at=built,
        size_kb=round(stat.st_size / 1024),
        hours_ago=round(age.total_seconds() / 3600, 1),
        stale=age > timedelta(hours=settings.export_fresh_hours),
    )


@router.get("/latest", summary="Download the current workbook")
def download(principal: CanViewDashboard) -> FileResponse:
    path = _latest()
    if path is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            # Says what is true and what to do, rather than "not found".
            detail=(
                "No workbook has been built yet. The nightly job writes it; "
                "run `python export/build_workbook.py` to build one now."
            ),
        )
    return FileResponse(
        path,
        media_type=XLSX,
        filename=path.name,
        # `attachment` so the browser saves it instead of trying to render a
        # binary in a tab.
        content_disposition_type="attachment",
    )
