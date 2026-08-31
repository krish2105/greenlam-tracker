"""Capability model — the server-side half of `packages/core/src/roles.ts`.

Both copies must agree. This one is the enforcing copy: the TypeScript version
exists to hide controls a person cannot use, which is a courtesy, not a gate.
`tests/test_roles.py` asserts the two files stay in step.

TWO LEVELS, DELIBERATELY

  * app        — everyone on the floor. Raise and work breakdown tickets, log
                 production and impregnation. Nothing else.
  * dashboard  — a named handful. Everything above, plus the dashboard, the
                 Excel import, the master lists and user management.

WHAT THIS REPLACED, AND WHY IT IS GONE RATHER THAN SWITCHED OFF

There were ten roles across three axes — capability × scope × resolution — so
that a shareholder could sit at the top of the org chart and see the LEAST
operational detail, while a manager scoped to one section saw only that
section. It was a good model for a group with five plants and a board.

It is the wrong model for one plant running one pilot, where the real access
question is "does this person need the dashboard, or just the app". Carrying
the machinery for the other model would mean every future query has to reason
about a scope and a resolution that always evaluate the same way.

The scoping and redaction code is DELETED, not disabled. Access control that
is half-removed is worse than none: the next person cannot tell which rules
still apply, and writes code assuming a guard that no longer guards.

When a second plant lands, this comes back — the database still carries
`plant_id` and `unit_id` on every row, which is the part that would have been
expensive to retrofit.
"""

from dataclasses import dataclass

ROLES: tuple[str, ...] = ("app", "dashboard")


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What a role may do. No org tier, no resolution — there are two levels."""

    raise_ticket: bool = False
    work_ticket: bool = False
    verify_close: bool = False
    log_production: bool = False
    view_dashboard: bool = False
    edit_masters: bool = False
    manage_users: bool = False
    unlock_users: bool = False
    export_data: bool = False
    import_data: bool = False


CAPABILITIES: dict[str, Capabilities] = {
    # Everyone. The whole point of the app is that reporting a breakdown is
    # never gated — a machine that stopped is a fact, not a privilege.
    "app": Capabilities(
        raise_ticket=True,
        work_ticket=True,
        verify_close=True,
        log_production=True,
    ),
    "dashboard": Capabilities(
        raise_ticket=True,
        work_ticket=True,
        verify_close=True,
        log_production=True,
        view_dashboard=True,
        edit_masters=True,
        manage_users=True,
        unlock_users=True,
        export_data=True,
        import_data=True,
    ),
}


def capabilities_of(role: str) -> Capabilities:
    try:
        return CAPABILITIES[role]
    except KeyError as exc:  # pragma: no cover - unreachable via the CHECK
        raise ValueError(f"Unknown role: {role}") from exc


def can(role: str, capability: str) -> bool:
    return getattr(capabilities_of(role), capability, False) is True


def sees_dashboard(role: str) -> bool:
    return can(role, "view_dashboard")
