from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _upload(client, name="demo_intake.sav"):
    response = client.post(f"/api/uploads/sample/{name}")
    assert response.status_code == 200, response.text
    data = response.json()
    return data


def test_health_and_formats(client):
    assert client.get("/api/health").json()["status"] == "ok"
    formats = client.get("/api/formats").json()["formats"]
    assert {item["id"] for item in formats} == {"csv", "xlsx", "sav", "dta"}
    assert all(item["limits"] for item in formats)


def test_samples_listed(client):
    names = {item["filename"] for item in client.get("/api/samples").json()["samples"]}
    assert {"demo_intake.sav", "demo_intake.dta"} <= names


def test_upload_rejects_wrong_extension(client):
    response = client.post(
        "/api/uploads",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


def test_upload_rejects_fake_extension(client):
    response = client.post(
        "/api/uploads",
        files={"file": ("fake.sav", b"not a spss file", "application/octet-stream")},
    )
    assert response.status_code == 422


def test_upload_preserves_original_and_interpretation(client):
    data = _upload(client, "demo_intake.dta")
    upload = data["upload"]
    interpretation = data["interpretation"]
    assert upload["file_type"] == "dta"
    assert interpretation["row_count"] == 12
    groups = {variable["name"]: variable for variable in interpretation["variables"]}
    assert groups["group"]["missing_rules"][0]["id"] == "extended:group:.a"
    assert groups["week"]["classification"] == "unsupported"
    assert interpretation["label_conflicts"]

    # Cells endpoint returns the three layers for one field.
    cells = client.get(
        f"/api/uploads/{upload['upload_id']}/cells",
        params={"column": "group", "limit": 20},
    ).json()
    last = cells["rows"][-1]
    assert last["raw"] == ".a"
    assert last["analysis"] is None
    assert last["state"] == "extended_missing"

    # The uploaded bytes are untouched on disk.
    from app import storage

    record = storage.load_upload(upload["upload_id"])
    assert hashlib.sha256(record.path.read_bytes()).hexdigest() == upload["sha256"]


def test_preview_requires_confirmation_token(client):
    data = _upload(client)
    upload_id = data["upload"]["upload_id"]
    spec = {
        "fields": [
            {
                "name": "group",
                "layers": ["raw", "analysis", "state"],
                "overrides": [{"rule_id": "user:group:9", "action": "set", "value": 1}],
            }
        ]
    }
    preview = client.post(f"/api/uploads/{upload_id}/preview", json=spec)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["confirmation_required"] is True
    assert body["fields"][0]["overrides"][0]["affected_rows"] == [11]
    assert body["fields"][0]["overrides"][0]["after"]["mean"] == 1.0

    # A wrong token is rejected.
    bad = client.post(
        f"/api/uploads/{upload_id}/results",
        json={"spec": spec, "format": "csv", "preview_token": "wrong"},
    )
    assert bad.status_code == 409

    # Without a token the result is still created (explicit API use).
    ok = client.post(
        f"/api/uploads/{upload_id}/results",
        json={"spec": spec, "format": "csv", "preview_token": body["preview_token"]},
    )
    assert ok.status_code == 200, ok.text
    manifest = ok.json()
    assert manifest["original"]["unchanged"] is True
    assert manifest["overrides"][0]["affected_rows"] == [11]
    assert manifest["exports"][0]["verification"]["ok"] is True


def test_result_is_queryable_and_downloadable(client):
    data = _upload(client)
    upload_id = data["upload"]["upload_id"]
    spec = {
        "fields": [
            {"name": "pid", "layers": ["raw", "analysis"]},
            {"name": "remark", "layers": ["raw", "label", "analysis", "state"]},
        ]
    }
    preview = client.post(f"/api/uploads/{upload_id}/preview", json=spec).json()
    created = client.post(
        f"/api/uploads/{upload_id}/results",
        json={"spec": spec, "format": "sav", "preview_token": preview["preview_token"]},
    ).json()
    result_id = created["result_id"]

    rows = client.get(f"/api/results/{result_id}/rows", params={"q": "拒答"}).json()
    assert rows["total"] == 4
    assert all(row["remark__raw"] == "拒答" for row in rows["rows"])
    assert all(row["remark__analysis"] is None for row in rows["rows"])

    page = client.get(
        f"/api/results/{result_id}/rows", params={"limit": 5, "offset": 10}
    ).json()
    assert page["total"] == 12
    assert len(page["rows"]) == 2

    download = client.get(f"/api/results/{result_id}/download")
    assert download.status_code == 200
    assert len(download.content) > 100

    recheck = client.get(f"/api/results/{result_id}/recheck").json()
    assert recheck["reports"][0]["ok"] is True


def test_additional_export_formats(client):
    data = _upload(client, "demo_intake.dta")
    upload_id = data["upload"]["upload_id"]
    spec = {"fields": [{"name": "age", "layers": ["raw", "label", "analysis", "state"]}]}
    preview = client.post(f"/api/uploads/{upload_id}/preview", json=spec).json()
    created = client.post(
        f"/api/uploads/{upload_id}/results",
        json={"spec": spec, "format": "csv", "preview_token": preview["preview_token"]},
    ).json()
    result_id = created["result_id"]

    for fmt in ("xlsx", "sav", "dta"):
        response = client.post(f"/api/results/{result_id}/exports/{fmt}")
        assert response.status_code == 200, response.text
    manifest = client.get(f"/api/results/{result_id}").json()
    assert {item["id"] for item in manifest["exports"]} == {"csv", "xlsx", "sav", "dta"}
    assert all(item["verification"]["ok"] for item in manifest["exports"])
    assert client.get(f"/api/results/{result_id}/download", params={"fmt": "dta"}).status_code == 200
    assert client.post(f"/api/results/{result_id}/exports/exe").status_code == 422


def test_what_if_does_not_change_original_interpretation(client):
    data = _upload(client, "demo_intake.dta")
    upload_id = data["upload"]["upload_id"]
    from app import storage

    original = storage.load_interpretation(upload_id)
    original_cells = json.dumps(original["cells"], ensure_ascii=False)
    record = storage.load_upload(upload_id)
    original_bytes = record.path.read_bytes()

    spec = {
        "fields": [
            {
                "name": "group",
                "layers": ["raw", "label", "analysis", "state"],
                "overrides": [{"rule_id": "extended:group:.a", "action": "set", "value": 2}],
            }
        ]
    }
    preview = client.post(f"/api/uploads/{upload_id}/preview", json=spec).json()
    first = client.post(
        f"/api/uploads/{upload_id}/results",
        json={"spec": spec, "format": "dta", "preview_token": preview["preview_token"]},
    ).json()
    second = client.post(
        f"/api/uploads/{upload_id}/results",
        json={"spec": spec, "format": "dta", "preview_token": preview["preview_token"]},
    ).json()
    assert first["result_id"] != second["result_id"]

    after = storage.load_interpretation(upload_id)
    assert json.dumps(after["cells"], ensure_ascii=False) == original_cells
    assert storage.load_upload(upload_id).path.read_bytes() == original_bytes

    # The second (untouched) result still reports .a for that cell.
    rows = client.get(f"/api/results/{first['result_id']}/rows").json()["rows"]
    assert rows[-1]["group__raw"] == ".a"
    assert rows[-1]["group__analysis"] == 2
    assert rows[-1]["group__state"] == "missing_extended:.a->set"

    # And the original upload still reports the missing state.
    cells = client.get(
        f"/api/uploads/{upload_id}/cells", params={"column": "group"}
    ).json()["rows"]
    assert cells[-1]["state"] == "extended_missing"
    assert cells[-1]["analysis"] is None


def test_preview_rejects_unknown_field(client):
    data = _upload(client)
    upload_id = data["upload"]["upload_id"]
    response = client.post(
        f"/api/uploads/{upload_id}/preview",
        json={"fields": [{"name": "does_not_exist"}]},
    )
    assert response.status_code == 422
    assert "未知字段" in response.json()["detail"]


def test_result_404_for_unknown_id(client):
    assert client.get("/api/results/" + "0" * 16).status_code == 404
    assert client.get("/api/uploads/" + "0" * 12).status_code == 404


def test_upload_listing_and_recent(client):
    data = _upload(client)
    listing = client.get("/api/uploads").json()["uploads"]
    assert any(item["upload_id"] == data["upload"]["upload_id"] for item in listing)
    again = client.get(f"/api/uploads/{data['upload']['upload_id']}").json()
    assert again["upload"]["original_name"] == "demo_intake.sav"


@pytest.mark.parametrize("name", ["demo_intake.sav", "demo_intake.dta"])
def test_all_formats_roundtrip_through_api(client, name):
    data = _upload(client, name)
    upload_id = data["upload"]["upload_id"]
    variables = [variable["name"] for variable in data["interpretation"]["variables"]]
    spec = {
        "fields": [
            {
                "name": variable,
                "layers": ["raw", "label", "analysis", "state"],
                "time_mode": "interpret",
            }
            for variable in variables
        ]
    }
    preview = client.post(f"/api/uploads/{upload_id}/preview", json=spec).json()
    assert preview["scope"]["layer_count"] == len(variables) * 4
    created = client.post(
        f"/api/uploads/{upload_id}/results",
        json={"spec": spec, "format": "sav", "preview_token": preview["preview_token"]},
    ).json()
    result_id = created["result_id"]
    for fmt in ("dta", "csv", "xlsx"):
        assert client.post(f"/api/results/{result_id}/exports/{fmt}").status_code == 200
    recheck = client.get(f"/api/results/{result_id}/recheck").json()
    assert all(report["ok"] for report in recheck["reports"]), recheck
