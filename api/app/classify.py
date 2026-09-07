"""Measuring a finished repair and banding it (V5 §5.8).

Its own module because two callers need it and neither should import the other:
the ticket router runs it at the half-close, and the correction router runs it
again when somebody fixes a wrong Correction Started or Correction Complete
time. A correction that moved a timestamp but left the old verdict standing
would be a half-applied fix — the visible number right, the derived one quietly
wrong, which is the worst of the three possible states.
"""

from __future__ import annotations

from sqlmodel import Session, select

from . import lifecycle, plant_settings
from .models import Section, Ticket, TicketPendingWindow


def classify(ticket: Ticket, session: Session) -> None:
    """Recompute `solve_minutes` and `criticality_calculated` in place.

    Safe to call at any point. A ticket with no Correction Started time — every
    row that came out of the old Excel register — lands on NULL rather than on
    a figure measured from somewhere else. Timing those from `raised_at` would
    count the wait for a technician as repair work and turn most of the history
    High.
    """
    windows = session.exec(
        select(TicketPendingWindow).where(TicketPendingWindow.ticket_id == ticket.id)
    ).all()
    pending = sum(w.minutes or 0 for w in windows)

    ticket.solve_minutes = lifecycle.solve_minutes(
        correction_started_at=ticket.repair_at,
        correction_complete_at=ticket.resolved_at,
        pending_minutes=pending,
    )

    section = session.get(Section, ticket.section_id)
    machine_class = lifecycle.machine_class(section.name if section else None)
    ticket.criticality_calculated = lifecycle.criticality_from_solve_time(
        ticket.solve_minutes,
        plant_settings.criticality_thresholds(session, ticket.plant_id, machine_class),
    )
