"""QR resolution, scan logging, and printable labels.

Addendum §1 calls this the highest-value addition, and the reasoning is about
seconds: picking a section, then finding the right machine in a list of twelve,
is where a 30-second ticket becomes a 90-second one — and 90 seconds is where
people go back to shouting across the floor.

THE TOKEN IS NOT A CREDENTIAL (§1.6)
It is printed on a wall. Anyone who can see the machine can read it. So `/s/
{token}` resolves the machine for *any* signed-in user in that plant, and
raising a ticket still goes through the normal capability check. What the token
buys is certainty about WHICH machine — hand-typed names produce "Press 4",
"press-4", "P4" and "Pres-4" as four different machines inside a month.

WHY NOT machine_id IN THE URL
Guessable, leaks row counts, and breaks if the database is ever re-seeded.
"""

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, status

from ..config import get_settings
from ..deps import CanManageUsers, PrincipalDep, SessionDep
from ..models import Machine, QrScan, Section, utcnow
from ..schemas_qr import LabelSheet, MachineLabel, ScanLogged, ScanResolution
from ..tenancy import assert_visible, scope

router = APIRouter(tags=["qr"])
settings = get_settings()

_SOURCE_Q = Query("in_app", pattern=r"^(in_app|native_camera)$")
_SECTION_Q = Query(None)


def _normalise_short(code: str) -> str:
    """'a7k2m9' and 'A7K2-M9' are the same label.

    The short code gets read aloud across a noisy hall and typed by someone in
    gloves. Anything but the characters is noise.
    """
    return "".join(ch for ch in code.upper() if ch.isalnum())


@router.get("/s/{token}", response_model=ScanResolution, summary="Resolve a scanned QR token")
def resolve_token(
    token: str, principal: PrincipalDep, session: SessionDep, source: str = _SOURCE_Q
) -> ScanResolution:
    """Turn a scanned token into a machine, and log the scan.

    Accepts either the 22-char QR token or the short fallback code, because a
    label in a laminate plant gets scratched, gets resin on it, and gets
    scrubbed — and a damaged sticker must never block anyone (§1.2).
    """
    machine = session.exec(scope(Machine, principal).where(Machine.qr_token == token)).first()

    if machine is None:
        cleaned = _normalise_short(token)
        candidates = session.exec(scope(Machine, principal)).all()
        machine = next(
            (m for m in candidates if _normalise_short(m.qr_short_code) == cleaned), None
        )

    if machine is None:
        # 404 with a usable next step, not a dead end. Someone is standing at a
        # machine holding a phone.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="That label is not recognised. Type the machine code instead, "
            "and tell your supervisor the sticker needs replacing.",
        )

    section = session.get(Section, machine.section_id)

    # Every scan logged. Two reasons (§1.5): it proves QR adoption at the pilot
    # review, and a machine that stops being scanned tells you its sticker
    # fell off.
    session.add(
        QrScan(
            plant_id=machine.plant_id,
            unit_id=machine.unit_id,
            machine_id=machine.id,
            user_id=principal.user_id,
            source=source,
            resulted_in=None,  # set when the scan turns into a ticket
        )
    )
    session.commit()

    return ScanResolution(
        machine_id=machine.id,
        machine_code=machine.code,
        machine_name=machine.name,
        section_id=machine.section_id,
        section_name=section.name if section else "—",
        short_code=machine.qr_short_code,
        criticality=machine.criticality,
    )


@router.post(
    "/qr/scans/{machine_id}/outcome", response_model=ScanLogged, summary="Record what a scan led to"
)
def record_outcome(
    machine_id: int,
    principal: PrincipalDep,
    session: SessionDep,
    resulted_in: str = Query(pattern=r"^(ticket|production|abandoned)$"),
) -> ScanLogged:
    """Close the loop on the most recent scan by this person for this machine.

    Lets the pilot review say "68% of tickets were raised by scanning, and those
    took 34 seconds against 81 typed" — which is the kind of number that gets a
    plant-wide rollout approved.
    """
    recent = session.exec(
        scope(QrScan, principal)
        .where(
            QrScan.machine_id == machine_id,
            QrScan.user_id == principal.user_id,
            QrScan.scanned_at >= utcnow() - timedelta(minutes=30),
        )
        .order_by(QrScan.scanned_at.desc())
    ).first()

    if recent is None:
        # Not an error: plenty of tickets are raised without scanning.
        return ScanLogged(recorded=False)

    recent.resulted_in = resulted_in
    session.add(recent)
    session.commit()
    return ScanLogged(recorded=True)


@router.get(
    "/qr/labels",
    response_model=LabelSheet,
    summary="Label data for printing (admin)",
)
def label_sheet(
    principal: PrincipalDep,
    session: SessionDep,
    section_id: int | None = _SECTION_Q,
) -> LabelSheet:
    """Everything needed to print a sheet of stickers.

    Returns data, not a PDF: the browser renders and prints it, which keeps
    workbook-class rendering off Render's 512 MB tier and means the print
    preview is the artifact — what you see is what goes on the wall.

    Physical spec is in the payload because getting it wrong wastes a print
    run: 40mm minimum, error correction H for scratches and resin, industrial
    heat-rated adhesive, and a 4-module quiet zone that scanners silently need.
    """
    if not principal.can("manage_users"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin only.")

    stmt = scope(Machine, principal).where(Machine.is_active.is_(True))
    if section_id is not None:
        stmt = stmt.where(Machine.section_id == section_id)

    machines = session.exec(stmt.order_by(Machine.section_id, Machine.code)).all()
    sections = {s.id: s for s in session.exec(scope(Section, principal)).all()}

    return LabelSheet(
        base_url=settings.base_url,
        count=len(machines),
        labels=[
            MachineLabel(
                machine_id=m.id,
                code=m.code,
                name_hi=m.name_hi,
                section_name=sections[m.section_id].name if m.section_id in sections else "—",
                short_code=m.qr_short_code,
                url=f"{settings.base_url}/s/{m.qr_token}",
                printed_at=m.label_printed_at,
            )
            for m in machines
        ],
    )


@router.post(
    "/qr/labels/printed",
    response_model=ScanLogged,
    summary="Mark labels as printed (admin)",
)
def mark_printed(
    machine_ids: list[int], principal: CanManageUsers, session: SessionDep
) -> ScanLogged:
    """Stamp `label_printed_at` so you can tell which machines are tagged.

    Without it nobody knows which stickers are actually on the wall, and the
    pilot starts with half the plant unlabelled — the kind of physical
    dependency that quietly delays a launch by a week (§5).
    """
    for machine_id in machine_ids:
        machine = session.get(Machine, machine_id)
        if machine is None:
            continue
        assert_visible(machine, principal)
        machine.label_printed_at = utcnow()
        session.add(machine)
    session.commit()
    return ScanLogged(recorded=True)
