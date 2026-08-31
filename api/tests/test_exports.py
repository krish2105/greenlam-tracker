"""Serving the nightly workbook.

The rule worth protecting here is negative: this endpoint must never BUILD a
workbook. Render free is 512 MB and 0.1 CPU, and openpyxl assembling a few
thousand rows would take the instance down at the exact moment somebody senior
clicked a button. So "no workbook yet" has to be a clean, explanatory 404
rather than an attempt to make one.
"""

import shutil

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.config import get_settings


class TestDownload:
    def test_no_workbook_yet_is_a_404_that_says_what_to_do(
        self, client: TestClient, plant_fixture, auth_headers, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(get_settings(), "export_dir", str(tmp_path))
        r = client.get("/exports/latest", headers=auth_headers("dashboard"))
        assert r.status_code == 404
        # Actionable, not just "not found".
        assert "build_workbook" in r.json()["detail"]

    def test_status_distinguishes_missing_from_stale(
        self, client: TestClient, plant_fixture, auth_headers, tmp_path, monkeypatch
    ):
        """Two different problems needing two different sentences.

        Conflating them is how somebody presents last week's numbers believing
        they are today's.
        """
        monkeypatch.setattr(get_settings(), "export_dir", str(tmp_path))
        body = client.get("/exports/status", headers=auth_headers("dashboard")).json()
        assert body["available"] is False
        assert body["stale"] is False

    def test_a_built_workbook_downloads_as_a_file(
        self, client: TestClient, plant_fixture, auth_headers, tmp_path, monkeypatch
    ):
        wb = Workbook()
        wb.active.append(["Sr No", "Date"])
        wb.save(tmp_path / "Greenlam_Test_Tracker.xlsx")
        monkeypatch.setattr(get_settings(), "export_dir", str(tmp_path))

        r = client.get("/exports/latest", headers=auth_headers("dashboard"))
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers["content-type"]
        # attachment, or a browser tries to render a binary in a tab.
        assert r.headers["content-disposition"].startswith("attachment")

    def test_the_staging_file_is_never_served(
        self, client: TestClient, plant_fixture, auth_headers, tmp_path, monkeypatch
    ):
        """The export writes to a dotfile and moves it into place. Mid-rebuild
        that dotfile is a truncated workbook, and serving it would hand someone
        a corrupt file that looks current."""
        wb = Workbook()
        wb.save(tmp_path / "Greenlam_Test_Tracker.xlsx")
        shutil.copy(
            tmp_path / "Greenlam_Test_Tracker.xlsx",
            tmp_path / ".Greenlam_Test_Tracker.xlsx.tmp",
        )
        monkeypatch.setattr(get_settings(), "export_dir", str(tmp_path))

        name = client.get("/exports/status", headers=auth_headers("dashboard")).json()[
            "filename"
        ]
        assert not name.startswith(".")

    def test_the_floor_cannot_download_it(
        self, client: TestClient, plant_fixture, auth_headers, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(get_settings(), "export_dir", str(tmp_path))
        assert client.get("/exports/latest", headers=auth_headers("app")).status_code == 403
        assert client.get("/exports/status", headers=auth_headers("app")).status_code == 403
