from __future__ import annotations

from pathlib import Path

import pytest

from app.compiler import SpecError, compile_result, parse_spec, preview, spec_token
from app.reader import read_file

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def dta():
    return read_file(str(ROOT / "samples" / "demo_intake.dta"), "demo_intake.dta")


@pytest.fixture(scope="module")
def sav():
    return read_file(str(ROOT / "samples" / "demo_intake.sav"), "demo_intake.sav")


def _spec(fields):
    return {"fields": fields}


def test_layers_are_separate_columns(dta):
    fields = parse_spec(dta, _spec([{"name": "group", "layers": ["raw", "label", "analysis", "state"]}]))
    compiled = compile_result(dta, fields)
    names = [column.name for column in compiled.columns]
    assert names == ["group__raw", "group__label", "group__analysis", "group__state"]
    raw, label, analysis, state = compiled.columns
    assert raw.values[-1] == ".a"
    assert label.values[-1] == ".a"
    assert analysis.values[-1] is None
    assert state.values[-1] == "missing_extended:.a"
    # The valid zero stays a valid labelled zero.
    assert raw.values[0] == 0
    assert analysis.values[0] == 0.0
    assert label.values[0] == "对照组（有效零）"


def test_override_set_creates_new_analysis_only(dta):
    spec = _spec(
        [
            {
                "name": "group",
                "layers": ["raw", "label", "analysis", "state"],
                "overrides": [{"rule_id": "extended:group:.a", "action": "set", "value": 1}],
            }
        ]
    )
    compiled = compile_result(dta, parse_spec(dta, spec))
    by_name = {column.name: column for column in compiled.columns}
    assert by_name["group__raw"].values[-1] == ".a"  # original code retained
    assert by_name["group__analysis"].values[-1] == 1.0
    assert by_name["group__label"].values[-1] == "干预组"
    assert by_name["group__state"].values[-1] == "missing_extended:.a->set"
    assert compiled.overrides_applied[0]["affected_rows"] == [11]


def test_override_valid_restores_spss_user_missing(sav):
    spec = _spec(
        [
            {
                "name": "remark",
                "layers": ["raw", "label", "analysis", "state"],
                "overrides": [{"rule_id": "user:remark:str:拒答", "action": "system"}],
            }
        ]
    )
    compiled = compile_result(sav, parse_spec(sav, spec))
    by_name = {column.name: column for column in compiled.columns}
    assert by_name["remark__analysis"].values[1] is None
    assert by_name["remark__raw"].values[1] == "拒答"
    assert by_name["remark__state"].values[1] == "missing_user->system"


def test_preview_reports_affected_rows_and_stats(dta):
    fields = [
        {
            "name": "age",
            "layers": ["raw", "label", "analysis", "state"],
            "overrides": [{"rule_id": "extended:age:.c", "action": "set", "value": 40}],
        }
    ]
    result = preview(dta, "sha", _spec(fields), available_formats=["csv", "sav"])
    rule = result["fields"][0]["overrides"][0]
    assert rule["affected_rows"] == [3, 9]
    assert rule["affected_count"] == 2
    assert rule["before"]["n"] == 0
    assert rule["after"]["n"] == 2
    assert rule["after"]["mean"] == 40.0
    assert result["scope"]["export_formats"] == ["csv", "sav"]
    assert result["confirmation_required"] is True
    assert result["original_immutable"] is True


def test_preview_token_tracks_spec(dta):
    base = _spec([{"name": "group", "layers": ["analysis"]}])
    changed = _spec(
        [
            {
                "name": "group",
                "layers": ["analysis"],
                "overrides": [{"rule_id": "extended:group:.a", "action": "set", "value": 2}],
            }
        ]
    )
    assert spec_token("abc", base) == spec_token("abc", {**base, "fields": [{"layers": ["analysis"], "name": "group"}]})
    assert spec_token("abc", base) != spec_token("abc", changed)
    assert spec_token("abc", base) != spec_token("def", base)


def test_preview_does_not_mutate_interpretation(dta):
    before = {name: list(dta.columns[name]["analysis"]) for name in ("age", "group")}
    preview(
        dta,
        "sha",
        _spec(
            [
                {
                    "name": "age",
                    "overrides": [{"rule_id": "extended:age:.c", "action": "set", "value": 1}],
                }
            ]
        ),
    )
    after = {name: list(dta.columns[name]["analysis"]) for name in ("age", "group")}
    assert before == after


def test_invalid_specs_are_rejected(dta):
    with pytest.raises(SpecError):
        parse_spec(dta, _spec([]))
    with pytest.raises(SpecError):
        parse_spec(dta, _spec([{"name": "nope"}]))
    with pytest.raises(SpecError):
        parse_spec(dta, _spec([{"name": "group", "layers": []}]))
    with pytest.raises(SpecError):
        parse_spec(dta, _spec([{"name": "group", "layers": ["bogus"]}]))
    with pytest.raises(SpecError):
        parse_spec(
            dta,
            _spec([{"name": "group", "overrides": [{"rule_id": "extended:group:.z", "action": "set", "value": 1}]}]),
        )
    with pytest.raises(SpecError):
        parse_spec(
            dta,
            _spec([{"name": "group", "overrides": [{"rule_id": "extended:group:.a", "action": "set"}]}]),
        )
    with pytest.raises(SpecError):
        parse_spec(dta, _spec([{"name": "pid", "time_mode": "numeric"}]))


def test_time_mode_numeric_keeps_storage_values(dta):
    compiled = compile_result(
        dta,
        parse_spec(dta, _spec([{"name": "visit_date", "layers": ["label", "analysis"], "time_mode": "numeric"}])),
    )
    by_name = {column.name: column for column in compiled.columns}
    assert by_name["visit_date__analysis"].values[0] == 21915.0
    assert by_name["visit_date__label"].values[0] == 21915.0


def test_unsupported_field_analysis_empty(dta):
    compiled = compile_result(
        dta, parse_spec(dta, _spec([{"name": "week", "layers": ["raw", "analysis", "state"]}]))
    )
    by_name = {column.name: column for column in compiled.columns}
    assert by_name["week__raw"].values[0] == 1.0
    assert by_name["week__analysis"].values[0] is None
    assert by_name["week__state"].values[0] == "unsupported"
    assert any("week" in note for note in compiled.notes)
