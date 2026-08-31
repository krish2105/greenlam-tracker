"""Master vocabularies for production and impregnation.

WHY THESE ARE TABLES AND NOT STRINGS

`production_logs` used to store `size`, `texture` and `thickness` as free text.
That is fine for a description and wrong for anything you intend to GROUP BY:
"Suede/Matte", "suede matte" and "Suede / Matte" are one texture to a person
and three rows to a database, so a reject breakdown by texture silently splits
itself and understates every line. Adding `design` as free text would have made
that worse, because design is the dimension with the most distinct values.

Every master here has the same shape as the ones that already existed
(sections, categories, reject reasons): trilingual name columns so a plant can
rename without a redeploy, a sort order, and an `is_active` flag rather than a
delete — history has to keep resolving names that are no longer offered.
"""

from decimal import Decimal

from sqlmodel import Field

from .base import PlantScoped


class _Vocab(PlantScoped):
    """Shared columns. Not a table itself — each concrete master is."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=120, index=True)
    name_hi: str | None = Field(default=None, max_length=120)
    name_hi_latn: str | None = Field(default=None, max_length=120)
    sort_order: int = Field(default=0)
    is_active: bool = Field(default=True)


class Design(_Vocab, table=True):
    """The décor — Walnut Oak, and so on. The highest-cardinality dimension."""

    __tablename__ = "designs"


class Size(_Vocab, table=True):
    """Sheet and roll cut size, e.g. 8x4 ft. Shared by both logs on purpose."""

    __tablename__ = "sizes"


class Texture(_Vocab, table=True):
    __tablename__ = "textures"


class Thickness(_Vocab, table=True):
    __tablename__ = "thicknesses"


class PaperCompany(_Vocab, table=True):
    """The paper supplier. Makes "which supplier gives us more rejects" answerable."""

    __tablename__ = "paper_companies"


class PaperGrade(_Vocab, table=True):
    """A paper grade, and the spec window its rolls are judged against.

    The limits live on the GRADE rather than in a global setting because an
    80 gsm décor paper and a 150 gsm kraft do not share an acceptable resin
    content. One global range would be wrong for both, and a range that is
    wrong is worse than no range — it trains people to ignore the warning.

    All four are nullable: a plant that has not yet decided its limits still
    gets to record RC and VC. Measuring first and setting limits once the
    normal range is known is the right order, and the alert simply stays quiet
    until then.
    """

    __tablename__ = "paper_grades"

    rc_min: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    rc_max: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    vc_min: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    vc_max: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)


def spec_breaches(
    grade: PaperGrade | None, rc: Decimal | None, vc: Decimal | None
) -> list[str]:
    """Which limits this roll misses, in words an operator can act on.

    Returns an empty list when the roll is fine, when the grade has no limits
    set, or when the reading is absent. Pure and free of the session so the
    rule can be tested directly — this is the judgement the whole feature rests
    on, and it should not need a database to exercise.
    """
    if grade is None:
        return []
    out: list[str] = []
    for label, value, low, high in (
        ("RC", rc, grade.rc_min, grade.rc_max),
        ("VC", vc, grade.vc_min, grade.vc_max),
    ):
        if value is None:
            continue
        if low is not None and value < low:
            out.append(f"{label} {value}% is below the {low}% minimum for {grade.name}")
        elif high is not None and value > high:
            out.append(f"{label} {value}% is above the {high}% maximum for {grade.name}")
    return out


__all__ = [
    "Design",
    "PaperCompany",
    "PaperGrade",
    "Size",
    "Texture",
    "Thickness",
    "spec_breaches",
]
