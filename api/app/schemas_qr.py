"""QR resolution and label shapes."""

from datetime import datetime

from pydantic import BaseModel


class ScanResolution(BaseModel):
    """What a scanned token resolves to.

    Deliberately thin: enough to prefill a ticket, nothing that would matter if
    the token leaked — because it is printed on a wall and therefore public.
    """

    machine_id: int
    machine_code: str
    machine_name: str
    section_id: int
    section_name: str
    short_code: str
    criticality: str


class ScanLogged(BaseModel):
    recorded: bool


class MachineLabel(BaseModel):
    machine_id: int
    code: str
    name_hi: str | None
    section_name: str
    short_code: str
    url: str
    printed_at: datetime | None


class LabelSheet(BaseModel):
    """Data for a printable sheet, not a rendered PDF.

    The browser prints it, which keeps rendering off Render's 512MB tier and
    makes the print preview the artifact — what you see is what goes on the
    wall.
    """

    base_url: str
    count: int
    labels: list[MachineLabel]
