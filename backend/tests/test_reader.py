from __future__ import annotations

from pathlib import Path

import pytest

from app.reader import read_file

ROOT = Path(__file__).resolve().parents[2]


def _read(name: str):
    path = ROOT / "samples" / name
    return read_file(str(path), name)


@pytest.fixture(scope="module")
def sav():
    return _read("demo_intake.sav")


@pytest.fixture(scope="module")
def dta():
    return _read("demo_intake.dta")


def test_sav_variables_and_storage(sav):
    assert sav.file_type == "sav"
    assert sav.row_count == 12
    names = [variable.name for variable in sav.variables]
    assert "note" in names and "remark" in names
    note = next(variable for variable in sav.variables if variable.name == "note")
    assert note.storage_type == "string"
    assert note.storage_width and note.storage_width > 100
    assert note.display_width == 40
    assert note.observed_max_bytes > note.observed_max_chars


def test_sav_user_missing_kept_apart_from_valid_zero(sav):
    group = sav.columns["group"]
    # A labelled, valid zero is still valid.
    assert group["state"][0] == "valid"
    assert group["raw"][0] == 0
    assert group["label"][0] == "对照组（有效零）"
    assert group["analysis"][0] == 0
    # 9 is user-missing only in `group`.
    assert group["state"][-1] == "user_missing"
    assert group["raw"][-1] == 9
    assert group["analysis"][-1] is None
    assert group["rule"][-1] == "user:group:9"


def test_same_code_has_different_meaning_per_variable(sav):
    assert sav.columns["group"]["label"][-1] == "拒答"
    age = sav.columns["age"]
    # 99 is a valid age, and 9 is a valid education year.
    assert age["analysis"][5] == 99
    assert sav.columns["edu_years"]["label"][0] == "九年级"
    conflicts = {item["value"] for item in sav.label_conflicts}
    assert {"9", "99"} <= conflicts


def test_sav_missing_range_and_string_missing(sav):
    age = sav.columns["age"]
    assert age["state"][3] == "user_missing"
    assert age["analysis"][3] is None
    assert age["rule"][3] == "user:age:range:-9:-1"
    # -3 has no label of its own but is still missing.
    assert age["state"][9] == "user_missing"
    remark = sav.columns["remark"]
    assert remark["state"][1] == "user_missing"
    assert remark["analysis"][1] is None
    # An empty string is system missing, not the user-defined "拒答".
    assert remark["state"][2] == "system_missing"


def test_sav_dates_use_spss_epoch(sav):
    visit = sav.columns["visit_date"]
    assert visit["label"][0] == "2020-01-01"
    assert visit["analysis"][0] == "2020-01-01"
    assert visit["label"][1] == "2020-02-29"  # leap day
    started = sav.columns["started_at"]
    assert started["analysis"][0].startswith("2020-01-01T")
    assert sav.columns["call_duration"]["analysis"][0] is not None


def test_dta_extended_missing_codes(dta):
    assert dta.file_type == "dta"
    group = dta.columns["group"]
    assert group["raw"][-1] == ".a"
    assert group["state"][-1] == "extended_missing"
    assert group["analysis"][-1] is None
    assert group["rule"][-1] == "extended:group:.a"
    assert dta.columns["satisfaction"]["raw"][1] == ".b"
    assert dta.columns["age"]["raw"][3] == ".c"
    assert dta.columns["age"]["raw"][9] == ".c"
    # The DTA keeps .a distinct from base missing.
    assert dta.columns["remark"]["state"][2] == "system_missing"


def test_dta_dates_use_stata_epoch(dta):
    visit = dta.columns["visit_date"]
    assert visit["label"][0] == "2020-01-01"
    assert visit["analysis"][0] == "2020-01-01"
    assert visit["label"][1] == "2020-02-29"
    started = dta.columns["started_at"]
    assert started["analysis"][0].startswith("2020-01-01T")
    period = dta.columns["period"]
    assert period["analysis"][0] == "2020-01-01"
    assert period["label"][0] == "2020m1"


def test_unsupported_week_format_is_refused(dta):
    week = next(variable for variable in dta.variables if variable.name == "week")
    assert week.classification == "unsupported"
    assert week.time is not None and not week.time.supported
    assert week.time.reason
    column = dta.columns["week"]
    assert column["state"][0] == "unsupported"
    assert column["analysis"][0] is None
    # The raw storage value is still there.
    assert column["raw"][0] == 1.0
