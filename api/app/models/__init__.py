"""All SQLModel tables. Importing this module registers every table on the
shared metadata, which is what Alembic's env.py autogenerate compares against.
"""

from ..roles import ROLES
from .base import PlantScoped, Timestamped, utcnow
from .corrections import ProductionCorrection, TicketCorrection
from .maintenance import (
    DOWNTIME_TYPES,
    EVENT_TYPES,
    PRIORITIES,
    RAISED_VIA,
    STAGES,
    Attachment,
    PmCompletion,
    PmSchedule,
    Ticket,
    TicketEvent,
    TicketMaterial,
    TicketPendingWindow,
)
from .masters import (
    Design,
    PaperCompany,
    PaperGrade,
    Size,
    Texture,
    Thickness,
    spec_breaches,
)
from .ops import (
    REVIEW_TYPES,
    RUN_STATUSES,
    ExportRun,
    ImportRun,
    ReviewRun,
    ShiftHandover,
)
from .org import (
    CRITICALITY,
    LANGUAGES,
    THEMES,
    Category,
    Machine,
    Plant,
    PlantSetting,
    QrScan,
    RejectReason,
    Section,
    Shift,
    Unit,
)
from .people import AuditLog, Device, RefreshToken, User
from .production import ImpregnationLog, ProductionLog, ResinBatch

__all__ = [
    # org
    "Plant",
    "ProductionCorrection",
    "TicketCorrection",
    "PlantSetting",
    "Unit",
    "Section",
    "Machine",
    "Shift",
    "Category",
    "RejectReason",
    "QrScan",
    # people
    "User",
    "Device",
    "RefreshToken",
    "AuditLog",
    # maintenance
    "Ticket",
    "TicketEvent",
    "TicketMaterial",
    "TicketPendingWindow",
    "Attachment",
    "PmSchedule",
    "PmCompletion",
    # production
    "ProductionLog",
    "ResinBatch",
    # ops
    "ExportRun",
    "ReviewRun",
    "Design",
    "PaperCompany",
    "PaperGrade",
    "Size",
    "Texture",
    "Thickness",
    "spec_breaches",
    "ImpregnationLog",
    "ShiftHandover",
    "ImportRun",
    # mixins + vocabularies
    "PlantScoped",
    "Timestamped",
    "utcnow",
    "ROLES",
    "STAGES",
    "PRIORITIES",
    "DOWNTIME_TYPES",
    "RAISED_VIA",
    "EVENT_TYPES",
    "CRITICALITY",
    "LANGUAGES",
    "THEMES",
    "RUN_STATUSES",
    "REVIEW_TYPES",
]
