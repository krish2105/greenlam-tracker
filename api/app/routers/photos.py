"""Photographs: the receipt, the part that arrived, the pack order (V5 §5.4, §6.2).

WHY A PHOTO IS ASKED FOR AT ALL

Two moments in the flowchart turn on somebody's word, and the photo is what
turns it into a record. "The part arrived" ends a pending window and restarts
the repair clock — it is the single claim in the whole lifecycle with a number
attached to it that nobody else witnesses. And "material was needed" is the
reason a repair took two days instead of an hour.

WHAT THIS REFUSES, AND WHY

  * Anything that is not an image. The camera on a phone produces JPEG or HEIC;
    a PDF here is somebody uploading the wrong thing, and it will be opened
    later by a person expecting a photograph.
  * Anything over 8 MB. A modern phone photo is 3-5 MB straight off the sensor
    and the app downscales before upload, so the cap is only ever hit by
    something that is not a phone photo.

The size limit is enforced by reading the stream rather than trusting
Content-Length, which a client controls.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlmodel import select

from ..deps import PrincipalDep, SessionDep
from ..models import Attachment, AttachmentBlob, ProductionLog, Ticket, User, utcnow
from ..tenancy import assert_visible

router = APIRouter(prefix="/photos", tags=["photos"])

KINDS = ("material", "part_arrived", "pack_order", "other")

# A phone photo off the sensor is 3-5 MB and the app downscales before sending,
# so this is only ever reached by something that is not a phone photo.
MAX_BYTES = 8 * 1024 * 1024

# HEIC included: it is what an iPhone produces by default, and a plant on BYOD
# phones is half iPhones.
# ruff B008 forbids calling File() in a default argument. Same singleton the
# import router uses.
_FILE = File(...)

ALLOWED = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}


class PhotoRead(BaseModel):
    id: int
    kind: str | None
    mime_type: str | None
    size_bytes: int | None
    uploaded_at: str
    uploaded_by_name: str | None


def _to_read(row: Attachment, names: dict) -> PhotoRead:
    return PhotoRead(
        id=row.id,
        kind=row.kind,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        uploaded_at=row.uploaded_at.isoformat(),
        uploaded_by_name=names.get(row.uploaded_by),
    )


async def _read_capped(file: UploadFile) -> bytes:
    """Read the upload, refusing past the cap.

    In chunks rather than `await file.read()`: the whole point of a limit is
    not to hold an unbounded upload in memory first, and Content-Length is a
    number the client chose.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(64 * 1024):
        total += len(chunk)
        if total > MAX_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="That photo is too large. Take it again from the app.",
            )
        chunks.append(chunk)
    if not chunks:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Empty file.")
    return b"".join(chunks)


@router.post(
    "/ticket/{ticket_id}",
    response_model=PhotoRead,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a photo to a ticket",
)
async def upload_for_ticket(
    ticket_id: UUID,
    principal: PrincipalDep,
    session: SessionDep,
    kind: str = "other",
    file: UploadFile = _FILE,
) -> PhotoRead:
    if not principal.can("work_ticket"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Your role does not have access to this."
        )
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(ticket, principal)

    if kind not in KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown photo kind.")
    if (file.content_type or "") not in ALLOWED:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That is not a photo. Use the camera rather than a file.",
        )

    data = await _read_capped(file)
    row = Attachment(
        plant_id=ticket.plant_id,
        unit_id=ticket.unit_id,
        ticket_id=ticket.id,
        kind=kind,
        # The bytes are in `attachment_blobs`; this names them so a future move
        # to R2 is a change of what the key points at, not of the schema.
        storage_key=f"db:ticket/{ticket.id}/{kind}",
        mime_type=file.content_type,
        size_bytes=len(data),
        uploaded_by=principal.user_id,
        uploaded_at=utcnow(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    session.add(AttachmentBlob(attachment_id=row.id, data=data))
    session.commit()

    user = session.get(User, principal.user_id)
    return _to_read(row, {principal.user_id: user.name if user else None})


@router.post(
    "/production/{log_id}",
    response_model=PhotoRead,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a photo to a production entry",
)
async def upload_for_production(
    log_id: UUID,
    principal: PrincipalDep,
    session: SessionDep,
    kind: str = "pack_order",
    file: UploadFile = _FILE,
) -> PhotoRead:
    if not principal.can("log_production"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Your role does not have access to this."
        )
    row = session.get(ProductionLog, log_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(row, principal)

    if kind not in KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown photo kind.")
    if (file.content_type or "") not in ALLOWED:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That is not a photo. Use the camera rather than a file.",
        )

    data = await _read_capped(file)
    att = Attachment(
        plant_id=row.plant_id,
        unit_id=row.unit_id,
        production_log_id=row.id,
        kind=kind,
        storage_key=f"db:production/{row.id}/{kind}",
        mime_type=file.content_type,
        size_bytes=len(data),
        uploaded_by=principal.user_id,
        uploaded_at=utcnow(),
    )
    session.add(att)
    session.commit()
    session.refresh(att)
    session.add(AttachmentBlob(attachment_id=att.id, data=data))
    session.commit()

    user = session.get(User, principal.user_id)
    return _to_read(att, {principal.user_id: user.name if user else None})


@router.get(
    "/ticket/{ticket_id}",
    response_model=list[PhotoRead],
    summary="Photos on a ticket",
)
def list_for_ticket(
    ticket_id: UUID, principal: PrincipalDep, session: SessionDep
) -> list[PhotoRead]:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(ticket, principal)

    rows = session.exec(
        select(Attachment)
        .where(Attachment.ticket_id == ticket_id)
        .order_by(Attachment.uploaded_at)
    ).all()
    names = {
        u.id: u.name
        for u in session.exec(
            select(User).where(User.id.in_({r.uploaded_by for r in rows} or {0}))
        ).all()
    }
    return [_to_read(r, names) for r in rows]


@router.get("/{photo_id}", summary="The photo itself")
def fetch(photo_id: int, principal: PrincipalDep, session: SessionDep) -> Response:
    """The bytes, with the tenant check the metadata row carries.

    Cached hard by the browser: an attachment is immutable — there is no
    endpoint that replaces one — so re-fetching it on every ticket open is
    bandwidth spent on a plant's mobile data for nothing.
    """
    row = session.get(Attachment, photo_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    assert_visible(row, principal)

    blob = session.get(AttachmentBlob, photo_id)
    if blob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")

    return Response(
        content=blob.data,
        media_type=row.mime_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
