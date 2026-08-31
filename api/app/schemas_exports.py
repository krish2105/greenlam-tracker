"""Wire shape for the workbook download."""

from datetime import datetime

from pydantic import BaseModel


class ExportStatusRead(BaseModel):
    """Whether a workbook exists, and whether it is worth trusting.

    `available` and `stale` are separate on purpose. "No workbook yet" and
    "a workbook from nine days ago" need different words in the interface —
    conflating them is how somebody presents last week's numbers believing
    they are today's.
    """

    available: bool
    stale: bool
    filename: str | None = None
    built_at: datetime | None = None
    size_kb: int | None = None
    hours_ago: float | None = None
