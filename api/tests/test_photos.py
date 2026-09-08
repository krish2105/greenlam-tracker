"""Photographs (V5 §5.4, §6.2).

Two moments in the lifecycle turn on somebody's word, and the photo is what
turns it into a record. "The part arrived" ends a pending window and restarts
the repair clock — it is the one claim in the whole flow with a number attached
that nobody else witnesses.
"""

import io

from fastapi.testclient import TestClient
from sqlmodel import select

from app.models import Attachment, AttachmentBlob

# A one-pixel PNG. Small enough to be obviously test data, real enough that the
# content type is not a lie.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100" "05fe02fe" "a7d1b0e40000000049454e44ae426082"
)


def _upload(client, tid, headers, *, kind="part_arrived", data=PNG, mime="image/png"):
    return client.post(
        f"/photos/ticket/{tid}?kind={kind}",
        files={"file": ("photo.png", io.BytesIO(data), mime)},
        headers=headers,
    )


class TestAPhotoIsStoredAndComesBack:
    def test_upload_then_fetch(
        self, client: TestClient, plant_fixture, auth_headers, session, seeded_ticket
    ):
        h = auth_headers("app")
        r = _upload(client, seeded_ticket, h)
        assert r.status_code == 201, r.text
        photo_id = r.json()["id"]
        assert r.json()["kind"] == "part_arrived"
        assert r.json()["size_bytes"] == len(PNG)

        got = client.get(f"/photos/{photo_id}", headers=h)
        assert got.status_code == 200
        assert got.content == PNG
        assert got.headers["content-type"].startswith("image/png")

    def test_the_bytes_live_apart_from_the_metadata(
        self, client: TestClient, plant_fixture, auth_headers, session, seeded_ticket
    ):
        """Its own table so a ticket list never ships the image data."""
        _upload(client, seeded_ticket, auth_headers("app"))
        att = session.exec(select(Attachment)).one()
        blob = session.get(AttachmentBlob, att.id)
        assert blob is not None
        assert blob.data == PNG

    def test_they_are_listed_against_the_ticket(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        h = auth_headers("app")
        _upload(client, seeded_ticket, h, kind="material")
        _upload(client, seeded_ticket, h, kind="part_arrived")

        rows = client.get(f"/photos/ticket/{seeded_ticket}", headers=h).json()
        assert {r["kind"] for r in rows} == {"material", "part_arrived"}
        assert all(r["uploaded_by_name"] for r in rows)


class TestWhatItRefuses:
    def test_a_pdf_is_not_a_photo(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        """Somebody uploading the wrong thing, and it will be opened later by a
        person expecting a photograph."""
        r = _upload(
            client, seeded_ticket, auth_headers("app"), data=b"%PDF-1.4", mime="application/pdf"
        )
        assert r.status_code == 422
        assert "not a photo" in r.json()["detail"]

    def test_an_empty_file_is_refused(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        r = _upload(client, seeded_ticket, auth_headers("app"), data=b"")
        assert r.status_code == 422

    def test_an_unknown_kind_is_refused(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        r = _upload(client, seeded_ticket, auth_headers("app"), kind="selfie")
        assert r.status_code == 422

    def test_something_too_large_is_refused_by_reading_not_by_trusting(
        self, client: TestClient, plant_fixture, auth_headers, seeded_ticket
    ):
        """Content-Length is a number the client chose."""
        from app.routers.photos import MAX_BYTES

        big = b"\x89PNG" + b"\x00" * (MAX_BYTES + 1024)
        r = _upload(client, seeded_ticket, auth_headers("app"), data=big)
        assert r.status_code == 413

    def test_somebody_who_does_not_work_tickets_cannot_attach(
        self, client: TestClient, plant_fixture, auth_headers, session, seeded_ticket
    ):
        from app.models import User, UserAccessArea

        uid = session.exec(select(User).where(User.employee_id == "T001")).one().id
        for row in session.exec(
            select(UserAccessArea).where(UserAccessArea.user_id == uid)
        ).all():
            session.delete(row)
        session.commit()
        session.add(UserAccessArea(user_id=uid, area="hpl_production"))
        session.commit()

        r = _upload(client, seeded_ticket, auth_headers("app"))
        assert r.status_code == 403


class TestProductionPhotos:
    def test_the_ac_room_pack_order(
        self, client: TestClient, plant_fixture, auth_headers
    ):
        h = auth_headers("operator")
        made = client.post(
            "/production",
            json={
                "machine_id": plant_fixture["machine"].id,
                "produced_qty": 400,
                "rejected_qty": 0,
            },
            headers=h,
        )
        assert made.status_code == 201, made.text
        log_id = made.json()["id"]

        r = client.post(
            f"/photos/production/{log_id}?kind=pack_order",
            files={"file": ("pack.png", io.BytesIO(PNG), "image/png")},
            headers=h,
        )
        assert r.status_code == 201, r.text
        assert r.json()["kind"] == "pack_order"
