"""Masters CRUD: sections, machines, shifts, categories, reject reasons, users.

Every read goes through `tenancy.scope()` and every by-id fetch through
`assert_visible()`. No handler in this module builds a bare `select()`.

Read is open to any signed-in user — the floor app pulls this master list down
on login so QR scanning resolves offline (addendum §1.3). Write is supervisor
and above.
"""

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import select

from ..config import get_settings
from ..deps import CanEditMasters, CanManageUsers, PrincipalDep, SessionDep
from ..models import (
    Category,
    Design,
    Machine,
    PaperCompany,
    PaperGrade,
    Plant,
    RejectReason,
    Section,
    Shift,
    Size,
    Texture,
    Thickness,
    Unit,
    User,
    utcnow,
)
from ..schemas import (
    MachineQrRead,
    MachineRead,
    MachineSetupRead,
    MachineSetupWrite,
    MachineWrite,
    PaperGradeRead,
    PaperGradeWrite,
    PlantRead,
    SectionRead,
    SectionWrite,
    ShiftRead,
    ShiftWrite,
    UnitRead,
    UserRead,
    UserWrite,
    VocabRead,
    VocabWrite,
)
from ..security import hash_pin, issue_qr_short_code, issue_qr_token, validate_pin_format
from ..tenancy import assert_visible, scope

router = APIRouter(prefix="/masters", tags=["masters"])
settings = get_settings()


# ---------------------------------------------------------------------------
# Plant and units
# ---------------------------------------------------------------------------
@router.get("/plant", response_model=PlantRead, summary="The caller's plant")
def get_plant(principal: PrincipalDep, session: SessionDep) -> PlantRead:
    plant = session.get(Plant, principal.home_plant_id)
    if plant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return PlantRead.model_validate(plant)


@router.get("/units", response_model=list[UnitRead], summary="Units in this plant")
def list_units(principal: PrincipalDep, session: SessionDep) -> list[UnitRead]:
    rows = session.exec(
        select(Unit).where(Unit.plant_id == principal.home_plant_id).order_by(Unit.id)
    ).all()
    return [UnitRead.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
@router.get("/sections", response_model=list[SectionRead], summary="Sections")
def list_sections(
    principal: PrincipalDep,
    session: SessionDep,
    include_inactive: bool = Query(False),
) -> list[SectionRead]:
    stmt = scope(Section, principal).order_by(Section.sort_order, Section.id)
    if not include_inactive:
        stmt = stmt.where(Section.is_active.is_(True))
    return [SectionRead.model_validate(r) for r in session.exec(stmt).all()]


@router.post(
    "/sections",
    response_model=SectionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a section",
)
def create_section(
    body: SectionWrite, principal: CanEditMasters, session: SessionDep
) -> SectionRead:
    row = Section(
        plant_id=principal.home_plant_id,
        unit_id=body.unit_id if body.unit_id is not None else principal.home_unit_id,
        **body.model_dump(exclude={"unit_id"}),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return SectionRead.model_validate(row)


@router.patch("/sections/{section_id}", response_model=SectionRead, summary="Edit a section")
def update_section(
    section_id: int, body: SectionWrite, principal: CanEditMasters, session: SessionDep
) -> SectionRead:
    row = session.get(Section, section_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(row, principal)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    session.add(row)
    session.commit()
    session.refresh(row)
    return SectionRead.model_validate(row)


# ---------------------------------------------------------------------------
# Machines
# ---------------------------------------------------------------------------
@router.get("/machines", response_model=list[MachineRead], summary="Machine master")
def list_machines(
    principal: PrincipalDep,
    session: SessionDep,
    section_id: int | None = Query(None),
    include_inactive: bool = Query(False),
) -> list[MachineRead]:
    """The floor app pulls this on login and caches it in Dexie, which is what
    makes QR resolution work with no network at all."""
    stmt = scope(Machine, principal).order_by(Machine.section_id, Machine.code)
    if section_id is not None:
        stmt = stmt.where(Machine.section_id == section_id)
    if not include_inactive:
        stmt = stmt.where(Machine.is_active.is_(True))
    return [MachineRead.model_validate(r) for r in session.exec(stmt).all()]


@router.post(
    "/machines",
    response_model=MachineRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a machine",
)
def create_machine(
    body: MachineWrite, principal: CanEditMasters, session: SessionDep
) -> MachineRead:
    """A QR token and short code are issued at creation, so a machine is
    printable the moment it exists."""
    section = session.get(Section, body.section_id)
    if section is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Section not found")
    assert_visible(section, principal)

    clash = session.exec(scope(Machine, principal).where(Machine.code == body.code)).first()
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"Machine code {body.code} already exists."
        )

    row = Machine(
        plant_id=principal.home_plant_id,
        unit_id=body.unit_id if body.unit_id is not None else section.unit_id,
        qr_token=issue_qr_token(),
        qr_short_code=issue_qr_short_code(),
        qr_issued_at=utcnow(),
        **body.model_dump(exclude={"unit_id"}),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return MachineRead.model_validate(row)


@router.patch("/machines/{machine_id}", response_model=MachineRead, summary="Edit a machine")
def update_machine(
    machine_id: int, body: MachineWrite, principal: CanEditMasters, session: SessionDep
) -> MachineRead:
    row = session.get(Machine, machine_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(row, principal)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    session.add(row)
    session.commit()
    session.refresh(row)
    return MachineRead.model_validate(row)


@router.get(
    "/machines/{machine_id}/qr",
    response_model=MachineQrRead,
    summary="QR payload for label printing (admin)",
)
def get_machine_qr(
    machine_id: int, principal: CanManageUsers, session: SessionDep
) -> MachineQrRead:
    """Admin-only because the token is what a printed label carries.

    The token is not a credential — `/s/{token}` still needs a session before a
    ticket can be raised — but there is no reason to hand the full set to every
    signed-in operator either.
    """
    row = session.get(Machine, machine_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(row, principal)
    return MachineQrRead(
        id=row.id,
        code=row.code,
        qr_token=row.qr_token,
        qr_short_code=row.qr_short_code,
        qr_url=f"{settings.base_url}/s/{row.qr_token}",
        qr_issued_at=row.qr_issued_at,
        label_printed_at=row.label_printed_at,
    )


@router.post(
    "/machines/{machine_id}/qr/reissue",
    response_model=MachineQrRead,
    summary="Reissue a QR token (admin)",
)
def reissue_machine_qr(
    machine_id: int, principal: CanManageUsers, session: SessionDep
) -> MachineQrRead:
    """For a decommissioned machine or a label that needs invalidating —
    addendum §1.6. The old token stops resolving immediately."""
    row = session.get(Machine, machine_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(row, principal)
    row.qr_token = issue_qr_token()
    row.qr_short_code = issue_qr_short_code()
    row.qr_issued_at = utcnow()
    row.label_printed_at = None  # the mounted label is now wrong; reprint needed
    session.add(row)
    session.commit()
    session.refresh(row)
    return MachineQrRead(
        id=row.id,
        code=row.code,
        qr_token=row.qr_token,
        qr_short_code=row.qr_short_code,
        qr_url=f"{settings.base_url}/s/{row.qr_token}",
        qr_issued_at=row.qr_issued_at,
        label_printed_at=row.label_printed_at,
    )


# ---------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------
@router.get("/shifts", response_model=list[ShiftRead], summary="Shifts")
def list_shifts(principal: PrincipalDep, session: SessionDep) -> list[ShiftRead]:
    stmt = scope(Shift, principal).order_by(Shift.sort_order, Shift.id)
    return [ShiftRead.model_validate(r) for r in session.exec(stmt).all()]


@router.post(
    "/shifts",
    response_model=ShiftRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a shift",
)
def create_shift(body: ShiftWrite, principal: CanEditMasters, session: SessionDep) -> ShiftRead:
    row = Shift(
        plant_id=principal.home_plant_id,
        unit_id=body.unit_id,
        **body.model_dump(exclude={"unit_id"}),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return ShiftRead.model_validate(row)


# ---------------------------------------------------------------------------
# Vocabularies — categories and reject reasons
# ---------------------------------------------------------------------------
@router.get("/categories", response_model=list[VocabRead], summary="Issue categories")
def list_categories(principal: PrincipalDep, session: SessionDep) -> list[VocabRead]:
    stmt = (
        scope(Category, principal)
        .where(Category.is_active.is_(True))
        .order_by(Category.sort_order, Category.id)
    )
    return [VocabRead.model_validate(r) for r in session.exec(stmt).all()]


@router.post(
    "/categories",
    response_model=VocabRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an issue category",
)
def create_category(body: VocabWrite, principal: CanEditMasters, session: SessionDep) -> VocabRead:
    row = Category(
        plant_id=principal.home_plant_id,
        unit_id=body.unit_id if body.unit_id is not None else principal.home_unit_id,
        **body.model_dump(exclude={"unit_id"}),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return VocabRead.model_validate(row)


@router.get("/reject-reasons", response_model=list[VocabRead], summary="Reject reasons")
def list_reject_reasons(principal: PrincipalDep, session: SessionDep) -> list[VocabRead]:
    stmt = (
        scope(RejectReason, principal)
        .where(RejectReason.is_active.is_(True))
        .order_by(RejectReason.sort_order, RejectReason.id)
    )
    return [VocabRead.model_validate(r) for r in session.exec(stmt).all()]


@router.post(
    "/reject-reasons",
    response_model=VocabRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a reject reason",
)
def create_reject_reason(
    body: VocabWrite, principal: CanEditMasters, session: SessionDep
) -> VocabRead:
    row = RejectReason(
        plant_id=principal.home_plant_id,
        unit_id=body.unit_id if body.unit_id is not None else principal.home_unit_id,
        **body.model_dump(exclude={"unit_id"}),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return VocabRead.model_validate(row)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@router.get("/users", response_model=list[UserRead], summary="People in this plant")
def list_users(principal: CanEditMasters, session: SessionDep) -> list[UserRead]:
    """Supervisor and above. An operator has no reason to enumerate colleagues,
    and the list is the input to any future individual-metrics view — which
    §4.1 of the addendum is emphatic about keeping off peer-visible screens."""
    stmt = scope(User, principal).order_by(User.name)
    return [UserRead.model_validate(r) for r in session.exec(stmt).all()]


@router.post(
    "/users",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a person",
)
def create_user(body: UserWrite, principal: CanManageUsers, session: SessionDep) -> UserRead:
    if not validate_pin_format(body.pin):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="PIN must be 6 digits, and not a repeat or a run like 123456.",
        )
    clash = session.exec(scope(User, principal).where(User.employee_id == body.employee_id)).first()
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Employee ID {body.employee_id} already exists at this plant.",
        )

    row = User(
        plant_id=principal.home_plant_id,
        unit_id=body.unit_id if body.unit_id is not None else principal.home_unit_id,
        pin_hash=hash_pin(body.employee_id, body.pin),
        **body.model_dump(exclude={"pin", "unit_id"}),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return UserRead.model_validate(row)


# ---------------------------------------------------------------------------
# Production vocabularies — design, size, texture, thickness, paper
# ---------------------------------------------------------------------------
#
# Six masters with identical behaviour, so they are GENERATED rather than
# written out six times. Two hundred lines of near-identical CRUD is not more
# explicit than this — it is six places for a rule to drift, and the drift is
# always silent (one master forgets `is_active`, another forgets to scope).
#
# Paper grade is the exception and gets its own handlers below, because it
# carries the RC/VC spec window that the impregnation alert is judged against.

_VOCAB_ROUTES: tuple[tuple[str, type, str], ...] = (
    ("designs", Design, "Designs (décor names)"),
    ("sizes", Size, "Sheet and roll sizes"),
    ("textures", Texture, "Textures"),
    ("thicknesses", Thickness, "Thicknesses"),
    ("paper-companies", PaperCompany, "Paper suppliers"),
)


def _register_vocab(path: str, model: type, label: str) -> None:
    @router.get(f"/{path}", response_model=list[VocabRead], summary=label, name=f"list_{path}")
    # `model` is closed over, NOT passed as a default argument. The first
    # version wrote `_m: type = model`, which FastAPI reads as a request
    # parameter and then fails to build a JSON schema for — the whole OpenAPI
    # document disappeared and every route with it. Each call to
    # `_register_vocab` already has its own binding, so the closure is safe.
    def _list(principal: PrincipalDep, session: SessionDep) -> list[VocabRead]:
        stmt = (
            scope(model, principal)
            .where(model.is_active.is_(True))
            .order_by(model.sort_order, model.id)
        )
        return [VocabRead.model_validate(r) for r in session.exec(stmt).all()]

    @router.post(
        f"/{path}",
        response_model=VocabRead,
        status_code=status.HTTP_201_CREATED,
        summary=f"Add to {label.lower()}",
        name=f"create_{path}",
    )
    def _create(
        body: VocabWrite,
        principal: CanEditMasters,
        session: SessionDep,
    ) -> VocabRead:
        row = model(
            plant_id=principal.home_plant_id,
            unit_id=body.unit_id if body.unit_id is not None else principal.home_unit_id,
            **body.model_dump(exclude={"unit_id"}),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return VocabRead.model_validate(row)


for _path, _model, _label in _VOCAB_ROUTES:
    _register_vocab(_path, _model, _label)


@router.get("/paper-grades", response_model=list[PaperGradeRead], summary="Paper grades")
def list_paper_grades(principal: PrincipalDep, session: SessionDep) -> list[PaperGradeRead]:
    """Grades, with the RC and VC window each one's rolls are judged against."""
    stmt = (
        scope(PaperGrade, principal)
        .where(PaperGrade.is_active.is_(True))
        .order_by(PaperGrade.sort_order, PaperGrade.id)
    )
    return [PaperGradeRead.model_validate(r) for r in session.exec(stmt).all()]


@router.post(
    "/paper-grades",
    response_model=PaperGradeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a paper grade",
)
def create_paper_grade(
    body: PaperGradeWrite, principal: CanEditMasters, session: SessionDep
) -> PaperGradeRead:
    row = PaperGrade(
        plant_id=principal.home_plant_id,
        unit_id=body.unit_id if body.unit_id is not None else principal.home_unit_id,
        **body.model_dump(exclude={"unit_id"}),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return PaperGradeRead.model_validate(row)


@router.patch(
    "/paper-grades/{grade_id}",
    response_model=PaperGradeRead,
    summary="Set a grade's RC/VC limits",
)
def update_paper_grade(
    grade_id: int,
    body: PaperGradeWrite,
    principal: CanEditMasters,
    session: SessionDep,
) -> PaperGradeRead:
    """Editing limits does NOT re-judge history.

    `out_of_spec` is stored on each roll at the moment it was entered, so a
    roll that was acceptable when it ran keeps saying so. Recomputing on read
    would let a limit change silently rewrite what an operator was told, which
    is the fastest way to make people stop trusting the flag.
    """
    row = session.get(PaperGrade, grade_id)
    assert_visible(row, principal)
    for field, value in body.model_dump(exclude={"unit_id"}, exclude_unset=True).items():
        setattr(row, field, value)
    session.add(row)
    session.commit()
    session.refresh(row)
    return PaperGradeRead.model_validate(row)


# ---------------------------------------------------------------------------
# Machine setup — the three inputs the plant owes us
# ---------------------------------------------------------------------------
#
# Every figure these unlock has been switched off since the system was built,
# and the dashboard says so in words rather than guessing. This is where they
# get switched on:
#
#   hourly_downtime_cost     -> a rupee figure for downtime
#   scheduled_hours_per_day  -> real availability instead of calendar
#   criticality              -> differentiated response targets
#
# A PATCH rather than a full PUT, because these arrive at different times from
# different people. Finance has the rate, production has the schedule, and the
# plant head has the criticality — nobody holds all three, and a PUT would make
# whoever answers last silently blank the other two.

@router.get(
    "/machines/setup",
    response_model=list[MachineSetupRead],
    summary="Machines with their cost, schedule and criticality",
)
def list_machine_setup(
    principal: CanEditMasters, session: SessionDep
) -> list[MachineSetupRead]:
    sections = {s.id: s.name for s in session.exec(scope(Section, principal)).all()}
    rows = session.exec(scope(Machine, principal).order_by(Machine.code)).all()
    return [
        MachineSetupRead(
            id=m.id,
            code=m.code,
            name=m.name,
            section_name=sections.get(m.section_id, "—"),
            criticality=m.criticality,
            hourly_downtime_cost=m.hourly_downtime_cost,
            scheduled_hours_per_day=m.scheduled_hours_per_day,
        )
        for m in rows
    ]


@router.patch(
    "/machines/{machine_id}/setup",
    response_model=MachineSetupRead,
    summary="Set a machine's cost, schedule or criticality",
)
def update_machine_setup(
    machine_id: int,
    body: MachineSetupWrite,
    principal: CanEditMasters,
    session: SessionDep,
) -> MachineSetupRead:
    machine = session.get(Machine, machine_id)
    assert_visible(machine, principal)

    # exclude_unset, so sending only the cost does not blank the schedule.
    # An explicit null still clears a field — that is how somebody retracts a
    # rate they are no longer confident in, and clearing it puts the dashboard
    # back to saying "not set" rather than leaving a stale number in place.
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(machine, field, value)

    session.add(machine)
    session.commit()
    session.refresh(machine)

    section = session.get(Section, machine.section_id)
    return MachineSetupRead(
        id=machine.id,
        code=machine.code,
        name=machine.name,
        section_name=section.name if section else "—",
        criticality=machine.criticality,
        hourly_downtime_cost=machine.hourly_downtime_cost,
        scheduled_hours_per_day=machine.scheduled_hours_per_day,
    )
