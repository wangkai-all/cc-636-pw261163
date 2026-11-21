from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyreadstat
import pytest

from app.compiler import compile_result, parse_spec
from app.export import build_export, verify
from app.reader import read_file

ROOT = Path(__file__).resolve().parents[2]


def _compiled(sample: str, spec: dict):
    path = ROOT / "samples" / sample
    read = read_file(str(path), sample)
    compiled = compile_result(read, parse_spec(read, spec))
    meta = read.to_metadata()
    return read, compiled, meta


BASE_SPEC = {
    "fields": [
        {"name": "pid", "layers": ["raw", "analysis"]},
        {"name": "group", "layers": ["raw", "label", "analysis", "state"]},
        {
            "name": "age",
            "layers": ["raw", "label", "analysis", "state"],
        },
        {
            "name": "satisfaction",
            "layers": ["raw", "label", "analysis", "state"],
        },
        {"name": "visit_date", "layers": ["raw", "label", "analysis", "state"]},
        {"name": "note", "layers": ["raw", "analysis"]},
        {"name": "remark", "layers": ["raw", "label", "analysis", "state"]},
    ]
}


def _build(tmp_path: Path, fmt: str, sample: str, source_type: str, spec=BASE_SPEC):
    read, compiled, meta = _compiled(sample, spec)
    target = tmp_path / f"result.{fmt}"
    build_export(
        fmt,
        target,
        compiled,
        meta,
        source_type=source_type,
        target_type=fmt,
    )
    assert target.exists() and target.stat().st_size > 0
    return target, compiled


@pytest.mark.parametrize("sample,source_type", [("demo_intake.sav", "sav"), ("demo_intake.dta", "dta")])
@pytest.mark.parametrize("fmt", ["csv", "xlsx", "sav", "dta"])
def test_export_roundtrip_verification(tmp_path, sample, source_type, fmt):
    target, compiled = _build(tmp_path, fmt, sample, source_type)
    report = verify(target, fmt, compiled)
    assert report["ok"], json.dumps(report, ensure_ascii=False, indent=2)
    assert report["checked_columns"] == len(compiled.columns)
    assert report["checked_cells"] >= compiled.row_count


def test_sav_export_keeps_labels_and_user_missing(tmp_path):
    target, compiled = _build(tmp_path, "sav", "demo_intake.sav", "sav")
    _frame, meta = pyreadstat.read_sav(
        str(target), user_missing=True, disable_datetime_conversion=True
    )
    labels = meta.variable_value_labels
    assert labels["group__raw"][9] == "拒答"
    assert labels["age__raw"][99] == "99 岁（有效值）"
    # User-defined missing is written back as an SPSS missing rule.  pyreadstat
    # may report a single string code as {lo, hi}; both forms mean the same.
    assert meta.missing_ranges.get("remark__raw") in (
        ["拒答"],
        [{"lo": "拒答", "hi": "拒答"}],
    )
    assert meta.missing_ranges.get("group__raw") in ([9], [{"lo": 9, "hi": 9}])
    # The raw date column keeps its source format, so SPSS re-displays it.
    assert meta.original_variable_types.get("visit_date__raw") == "DATE11"


def test_dta_export_keeps_extended_missing_codes(tmp_path):
    target, compiled = _build(tmp_path, "dta", "demo_intake.dta", "dta")
    frame, meta = pyreadstat.read_dta(
        str(target), user_missing=True, disable_datetime_conversion=True
    )
    assert list(frame["group__raw"])[-1] == "a"
    assert list(frame["age__raw"])[3] == "c"
    assert list(frame["satisfaction__raw"])[1] == "b"
    assert "." + meta.missing_user_values["group__raw"][0] in {".a", "a"}
    assert meta.original_variable_types.get("visit_date__raw") == "%td"


def test_dta_export_from_sav_does_not_invent_extended_codes(tmp_path):
    target, compiled = _build(tmp_path, "dta", "demo_intake.sav", "sav")
    frame, _meta = pyreadstat.read_dta(
        str(target), user_missing=True, disable_datetime_conversion=True
    )
    assert not any(isinstance(value, str) for value in frame["group__raw"])


def test_csv_sidecar_holds_schema(tmp_path):
    target, compiled = _build(tmp_path, "csv", "demo_intake.dta", "dta")
    sidecar = target.with_suffix(".schema.json")
    assert sidecar.exists()
    schema = json.loads(sidecar.read_text("utf-8"))
    assert schema["row_count"] == compiled.row_count
    assert [column["name"] for column in schema["columns"]] == [
        column.name for column in compiled.columns
    ]
    text = target.read_text("utf-8-sig")
    assert "拒答" in text


def test_xlsx_has_dictionary_sheet(tmp_path):
    target, compiled = _build(tmp_path, "xlsx", "demo_intake.dta", "dta")
    dictionary = pd.read_excel(target, sheet_name="dictionary", dtype=str)
    assert set(dictionary["列名"]) == {column.name for column in compiled.columns}
    readme = pd.read_excel(target, sheet_name="readme")
    assert int(readme.loc[readme["项目"] == "行数", "值"].iloc[0]) == compiled.row_count


def test_verification_detects_tampered_value(tmp_path):
    target, compiled = _build(tmp_path, "csv", "demo_intake.sav", "sav")
    text = target.read_text("utf-8-sig")
    # Change the first data row's pid from 1 to 999.
    lines = text.splitlines()
    lines[1] = "999" + lines[1][1:] if lines[1].startswith("1") else lines[1]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    report = verify(target, "csv", compiled)
    assert not report["ok"]
    assert report["value_mismatches"]


def test_verification_detects_missing_dta_code(tmp_path):
    target, compiled = _build(tmp_path, "dta", "demo_intake.dta", "dta")
    # Rewrite the file without extended codes by exporting the same layers as a
    # plain frame; verification must notice .a is gone.
    _frame, meta = pyreadstat.read_dta(
        str(target), user_missing=True, disable_datetime_conversion=True
    )
    pyreadstat.write_dta(_frame.replace({"a": None}), str(target), version=15)
    report = verify(target, "dta", compiled)
    assert not report["ok"]


def test_override_export_keeps_raw_and_analysis_distinct(tmp_path):
    spec = {
        "fields": [
            {
                "name": "group",
                "layers": ["raw", "label", "analysis", "state"],
                "overrides": [{"rule_id": "extended:group:.a", "action": "set", "value": 2}],
            }
        ]
    }
    for fmt in ("sav", "dta"):
        target, compiled = _build(tmp_path, fmt, "demo_intake.dta", "dta", spec=spec)
        report = verify(target, fmt, compiled)
        assert report["ok"], json.dumps(report, ensure_ascii=False, indent=2)
        reader = pyreadstat.read_sav if fmt == "sav" else pyreadstat.read_dta
        frame, _meta = reader(str(target), user_missing=True, disable_datetime_conversion=True)
        assert frame["group__analysis"].tolist()[-1] == 2
        if fmt == "dta":
            assert frame["group__raw"].tolist()[-1] == "a"
