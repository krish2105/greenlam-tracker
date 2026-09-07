"""Access areas — the server-side half of `packages/core/src/roles.ts`.

Both copies must agree. This one is the enforcing copy: the TypeScript version
exists to hide controls a person cannot use, which is a courtesy, not a gate.
`tests/test_access_areas.py` asserts the two files stay in step.

SIX AREAS, HELD IN ANY COMBINATION

V5 §3 names them and is explicit that they are independent grants rather than a
ladder. A shift supervisor who also logs production holds two areas, not a
compromise between two roles; there is no cap and no implied ordering. Admin
switches on whichever apply to each person.

    hpl_production  raise tickets, submit production data, read the daily log
    maintenance     acknowledge, work and close tickets; the ticket summary
    supervisor      notified about flagged tickets; reopen; reassign
    manager         the same, plus handing a ticket to a named person
    dashboard       the analytics dashboards and their exports
    admin           approve accounts, grant areas, edit the master lists

A person holds a SET of these, and their capabilities are the union. Nobody
inherits anything: an account with `dashboard` alone can read the board and
cannot touch a ticket, which is exactly what a plant head usually wants.

WHAT THIS REPLACED

`role`, one string of two values — `app` and `dashboard`. It was the right
model while the only access question was "does this person need the board", and
the wrong one the moment V5 asked for a supervisor who is notified about
flagged tickets but does not work them.

The column is DELETED in migration 0014, not left unread. A column nothing
consults still looks like it means something, and the thing it would appear to
mean is the one thing it no longer decides.

WHY REOPEN IS ITS OWN CAPABILITY

It used to travel with closing, under `verify_close`, on the reasoning that
whoever signs a ticket off should not be whoever fixed it. V5 §5.4 settles both
halves differently: every ticket is self-closed by the person who solved it, so
closing is part of working; and reopening is open to Maintenance, Supervisor,
Manager and Admin alike, because the only real safety net against a premature
close is somebody noticing the machine is still broken, and that net is worth
keeping wide.
"""

from dataclasses import dataclass

AREAS: tuple[str, ...] = (
    "hpl_production",
    "maintenance",
    "supervisor",
    "manager",
    "dashboard",
    "admin",
)


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What somebody may do. The union over every area they hold."""

    raise_ticket: bool = False
    work_ticket: bool = False
    reopen_ticket: bool = False
    # Handing a ticket to a named person on somebody else's behalf (V5 §15.5).
    # Distinct from an engineer passing their own ticket on at shift change,
    # which is part of working it.
    reassign_ticket: bool = False
    log_production: bool = False
    view_dashboard: bool = False
    edit_masters: bool = False
    approve_users: bool = False
    manage_users: bool = False
    unlock_users: bool = False
    export_data: bool = False
    import_data: bool = False


# Raising a breakdown is on every area on purpose. A machine that stopped is a
# fact, not a privilege (CLAUDE.md), and the person standing next to it is
# whoever happens to be standing next to it. The one account that cannot raise
# a ticket is one holding no areas at all — a signup nobody has approved, or an
# account whose access was deliberately emptied.
CAPABILITIES: dict[str, Capabilities] = {
    "hpl_production": Capabilities(
        raise_ticket=True,
        log_production=True,
    ),
    "maintenance": Capabilities(
        raise_ticket=True,
        work_ticket=True,
        reopen_ticket=True,
    ),
    "supervisor": Capabilities(
        raise_ticket=True,
        reopen_ticket=True,
        reassign_ticket=True,
    ),
    "manager": Capabilities(
        raise_ticket=True,
        reopen_ticket=True,
        reassign_ticket=True,
    ),
    # Reading the board is not working the floor. Somebody who holds only this
    # can see every number and cannot acknowledge a ticket, which is what a
    # plant head or a visiting director actually needs.
    "dashboard": Capabilities(
        view_dashboard=True,
        export_data=True,
    ),
    "admin": Capabilities(
        raise_ticket=True,
        reopen_ticket=True,
        reassign_ticket=True,
        edit_masters=True,
        approve_users=True,
        manage_users=True,
        unlock_users=True,
        import_data=True,
    ),
}

_FIELDS = tuple(Capabilities.__dataclass_fields__)
NONE = Capabilities()


def capabilities_of(areas: object) -> Capabilities:
    """The union of every area held. Unknown areas contribute nothing.

    An unknown name is ignored rather than raising: the database CHECK is what
    keeps the column honest, and a request that 500s because somebody typed a
    new area into a row is a worse failure than that area simply not granting
    anything yet.
    """
    held = [CAPABILITIES[a] for a in (areas or ()) if a in CAPABILITIES]
    if not held:
        return NONE
    return Capabilities(**{f: any(getattr(c, f) for c in held) for f in _FIELDS})


def can(areas: object, capability: str) -> bool:
    return getattr(capabilities_of(areas), capability, False) is True


def sees_dashboard(areas: object) -> bool:
    return can(areas, "view_dashboard")
