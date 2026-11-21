"""Export compiled results and verify the round-trip.

The export never overwrites the upload or its interpretation.  Each format
carries the layer columns plus, where the format allows, the value labels,
missing rules, formats and display widths that give those values meaning.

``verify`` re-reads the produced file and compares values, labels and missing
semantics against the compiled result, returning a structured report.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import pyreadstat

from .compiler import CompiledColumn, CompiledResult
from .dta_io import patch_extended_missing
from .values import canonical_number, raw_string

STATE_LABEL = "缺失/有效性"


def _is_numeric(column: CompiledColumn) -> bool:
    """Numeric-ness follows the declared layer dtype, not observed values.

    A raw layer of a numeric variable stays numeric even when it carries Stata
    extended missing codes (``.a``): those cells are exported as system missing
    and, for DTA targets, patched back into the original code.
    """

    if column.layer in {"state", "label"}:
        return False
    return column.dtype == "number"


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return float(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _label_map(column: CompiledColumn) -> dict[float, str]:
    labels: dict[float, str] = {}
    for item in column.value_labels:
        if item.get("numeric") is None:
            continue
        try:
            labels[float(item["numeric"])] = str(item["label"])
        except (TypeError, ValueError):
            continue
    return labels


def _string_label_map(column: CompiledColumn) -> dict[str, str]:
    labels: dict[str, str] = {}
    for item in column.value_labels:
        if item.get("numeric") is not None:
            continue
        labels[str(item["value"])] = str(item["label"])
    return labels


def _output_frame(columns: list[CompiledColumn]) -> pd.DataFrame:
    data: dict[str, Any] = {}
    for column in columns:
        if _is_numeric(column):
            values = []
            flagged: list[int] = []
            for row, value in enumerate(column.values):
                number = _to_float(value)
                if number is None and isinstance(value, str) and value.startswith("."):
                    flagged.append(row)
                values.append(number)
            series = pd.Series(values, dtype="float64")
            if flagged:
                series.attrs["stata_missing_rows"] = flagged
            data[column.name] = series
        else:
            data[column.name] = pd.Series(
                ["" if value is None else str(value) for value in column.values],
                dtype="object",
            )
    return pd.DataFrame(data)


def _spss_missing_ranges(column: CompiledColumn) -> list[Any]:
    rules: list[Any] = []
    for rule in column.missing_rules:
        kind = rule.get("kind")
        if kind == "system":
            continue
        if kind == "extended":
            continue
        if rule.get("value_kind") == "string":
            if rule.get("code") is not None:
                rules.append(str(rule["code"]))
            continue
        lo = rule.get("low")
        hi = rule.get("high")
        if lo is None:
            continue
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            if float(lo) == float(hi):
                rules.append(int(lo) if float(lo).is_integer() else float(lo))
            else:
                rules.append(
                    {
                        "lo": int(lo) if float(lo).is_integer() else float(lo),
                        "hi": int(hi) if float(hi).is_integer() else float(hi),
                    }
                )
    return rules


def _variable_label(column: CompiledColumn) -> str:
    text = column.title
    return text[:255]


def _spss_string_missing(column: CompiledColumn) -> list[str]:
    return [
        str(rule["code"])
        for rule in column.missing_rules
        if rule.get("kind") == "user" and rule.get("value_kind") == "string" and rule.get("code")
    ]


def _spss_source_format(column: CompiledColumn, source_format: Optional[str]) -> Optional[str]:
    if column.layer != "raw" or not source_format:
        return None
    if source_format.startswith("%"):
        return None
    return source_format


def export_sav(path: Path, result: CompiledResult, read_meta: dict[str, Any]) -> dict[str, Any]:
    frame = _output_frame(result.columns)
    labels: dict[str, str] = {}
    value_labels: dict[str, dict[Any, str]] = {}
    missing_ranges: dict[str, list[Any]] = {}
    display_widths: dict[str, int] = {}
    source_formats: dict[str, str] = {}
    notes: list[str] = []

    variables = {item["name"]: item for item in read_meta.get("variables", [])}
    for column in result.columns:
        labels[column.name] = _variable_label(column)
        if _is_numeric(column):
            numeric_labels = _label_map(column)
            if numeric_labels:
                value_labels[column.name] = numeric_labels
            if column.layer == "raw":
                rules = _spss_missing_ranges(column)
                if rules:
                    missing_ranges[column.name] = rules
            source_variable = variables.get(column.source, {})
            source_format = _spss_source_format(column, source_variable.get("source_format"))
            if source_format:
                source_formats[column.name] = source_format
        else:
            string_labels = _string_label_map(column)
            if string_labels and column.layer == "raw":
                value_labels[column.name] = string_labels
            if column.layer == "raw":
                string_rules = _spss_string_missing(column)
                if string_rules:
                    missing_ranges[column.name] = string_rules
            width = max(
                (len(str(value)) for value in column.values if value not in (None, "")),
                default=0,
            )
            display_widths[column.name] = min(max(width, 1), 255)

    pyreadstat.write_sav(
        frame,
        str(path),
        column_labels=labels,
        variable_value_labels=value_labels or None,
        missing_ranges=missing_ranges or None,
        variable_display_width=display_widths or None,
        variable_format=source_formats or None,
    )
    if value_labels:
        notes.append("导出的 SAV 保留了各列的变量标签与值标签。")
    if missing_ranges:
        notes.append("原始值列按源字段的缺失规则写入 SPSS 用户定义缺失（离散值/范围/字符串）。")
    return {"notes": notes}


def _stata_format(column: CompiledColumn, source_format: Optional[str]) -> Optional[str]:
    if column.layer == "raw" and source_format and source_format.startswith("%"):
        return source_format
    return None


def export_dta(
    path: Path, result: CompiledResult, read_meta: dict[str, Any], *, patch_ext: bool
) -> dict[str, Any]:
    frame = _output_frame(result.columns)
    labels = {column.name: _variable_label(column) for column in result.columns}
    value_labels: dict[str, dict[Any, str]] = {}
    formats: dict[str, str] = {}
    variables = {item["name"]: item for item in read_meta.get("variables", [])}
    notes: list[str] = []
    patched: list[tuple[int, list[int], str]] = []

    for index, column in enumerate(result.columns):
        if _is_numeric(column):
            numeric_labels = _label_map(column)
            if numeric_labels:
                value_labels[column.name] = {
                    int(key) if float(key).is_integer() else key: value
                    for key, value in numeric_labels.items()
                }
            source_variable = variables.get(column.source, {})
            fmt = _stata_format(column, source_variable.get("source_format"))
            if fmt:
                formats[column.name] = fmt
        if column.layer == "raw" and patch_ext:
            groups: dict[str, list[int]] = {}
            for row, value in enumerate(column.values):
                if isinstance(value, str) and value.startswith(".") and len(value) == 2:
                    groups.setdefault(value, []).append(row)
            for code, rows in groups.items():
                patched.append((index, rows, code))

    pyreadstat.write_dta(
        frame,
        str(path),
        version=15,
        column_labels=labels,
        variable_value_labels=value_labels or None,
        variable_format=formats or None,
    )
    for index, rows, code in patched:
        patch_extended_missing(path, index, rows, code)
    if patched:
        notes.append(
            "Stata 扩展缺失码已按原编码写回（.a-.z），重新读取时用 user_missing=True 可还原。"
        )
    notes.append(
        "Stata 不含 SPSS 的显示宽度概念；字符串按实际内容保存，显示宽度差异记录在清单中。"
    )
    return {"notes": notes}


def export_csv(
    path: Path,
    result: CompiledResult,
    read_meta: dict[str, Any],
    *,
    sidecar: Path,
    patch_ext: bool,
) -> dict[str, Any]:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([column.name for column in result.columns])
        for row in range(result.row_count):
            writer.writerow(
                [
                    _cell_text(column.values[row])
                    for column in result.columns
                ]
            )
    from .storage import write_json

    write_json(
        sidecar,
        {
            "format": "csv",
            "columns": result.schema,
            "row_count": result.row_count,
            "notes": [
                "CSV 不携带标签/缺失规则；schema.json 与本次结果一起保存，"
                "重新读取时用它恢复值与含义。",
            ],
        },
    )
    return {
        "notes": [
            "CSV 用 UTF-8 BOM 编码，缺失为空字符串；同目录的 schema.json 保存标签与缺失规则。"
        ],
        "sidecar": sidecar.name,
    }


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return canonical_number(value)
    return str(value)


def export_xlsx(path: Path, result: CompiledResult, read_meta: dict[str, Any]) -> dict[str, Any]:
    # Text frame so raw extended codes (".a") and dates stay exactly as shown;
    # the dictionary sheet restores their meaning.
    frame = pd.DataFrame(
        {
            column.name: [
                _cell_text(value) for value in column.values
            ]
            for column in result.columns
        }
    )
    dictionary_rows = []
    for column in result.columns:
        labels = "；".join(
            f"{item['value']}={item['label']}" for item in column.value_labels
        )
        rules = "；".join(
            f"{rule['kind']}:{rule.get('code') or (str(rule.get('low')) + '..' + str(rule.get('high')))}"
            for rule in column.missing_rules
            if rule.get("kind") != "system"
        )
        dictionary_rows.append(
            {
                "列名": column.name,
                "来源字段": column.source,
                "层": column.layer,
                "标题": column.title,
                "类型": column.dtype,
                "值标签": labels,
                "缺失规则": rules,
                "时间格式": (column.time or {}).get("source_format") or "",
                "说明": column.description,
            }
        )
    dictionary = pd.DataFrame(dictionary_rows)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="data", index=False)
        dictionary.to_excel(writer, sheet_name="dictionary", index=False)
        read_me = pd.DataFrame(
            {
                "项目": ["行数", "列数", "说明"],
                "值": [
                    result.row_count,
                    len(result.columns),
                    "data 为编译后的层列；dictionary 为标签与缺失规则。",
                ],
            }
        )
        read_me.to_excel(writer, sheet_name="readme", index=False)
    return {
        "notes": [
            "XLSX 含 data / dictionary / readme 三个工作表；dictionary 恢复标签与缺失含义。"
        ]
    }


def build_export(
    fmt: str,
    path: Path,
    result: CompiledResult,
    read_meta: dict[str, Any],
    *,
    source_type: str,
    target_type: str,
) -> dict[str, Any]:
    if fmt == "sav":
        return export_sav(path, result, read_meta)
    if fmt == "dta":
        return export_dta(
            path,
            result,
            read_meta,
            patch_ext=(source_type == "dta" and target_type == "dta"),
        )
    if fmt == "csv":
        return export_csv(
            path,
            result,
            read_meta,
            sidecar=path.with_suffix(".schema.json"),
            patch_ext=False,
        )
    if fmt == "xlsx":
        return export_xlsx(path, result, read_meta)
    raise ValueError(f"不支持的导出格式：{fmt}")



def verify(path: Path, fmt: str, result: CompiledResult) -> dict[str, Any]:
    """Re-read the export and compare values, labels and missing semantics."""

    report: dict[str, Any] = {
        "format": fmt,
        "ok": True,
        "value_mismatches": [],
        "label_mismatches": [],
        "missing_mismatches": [],
        "column_mismatches": [],
        "notes": [],
        "checked_columns": 0,
        "checked_cells": 0,
    }

    try:
        if fmt in {"sav", "dta"}:
            reader = pyreadstat.read_sav if fmt == "sav" else pyreadstat.read_dta
            frame, meta = reader(
                str(path),
                user_missing=True,
                # Keep storage numbers raw so raw-layer values can be compared;
                # date meaning is checked through the labels/formats below.
                disable_datetime_conversion=True,
                output_format="dict",
            )
            actual_columns = list(frame.keys())
            _verify_binary(frame, meta, result, report, fmt)
        elif fmt == "csv":
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            actual_columns = list(frame.columns)
            for column in result.columns:
                if column.name not in frame.columns:
                    report["column_mismatches"].append({"column": column.name, "reason": "missing"})
                    continue
                actual = ["" if value is None else str(value) for value in frame[column.name].tolist()]
                expected = [_cell_text(value) for value in column.values]
                for row, (left, right) in enumerate(zip(expected, actual)):
                    report["checked_cells"] += 1
                    if left != right:
                        report["value_mismatches"].append(
                            {"column": column.name, "row": row, "expected": left, "actual": right}
                        )
                report["checked_columns"] += 1
            report["notes"].append(
                "CSV 的标签与缺失规则由同目录 schema.json 保存；本报告只核对数据单元格。"
            )
        elif fmt == "xlsx":
            data = pd.read_excel(path, sheet_name="data", dtype=object)
            dictionary = pd.read_excel(path, sheet_name="dictionary", dtype=str, keep_default_na=False)
            actual_columns = list(data.columns)
            for column in result.columns:
                if column.name not in data.columns:
                    report["column_mismatches"].append({"column": column.name, "reason": "missing"})
                    continue
                actual = [
                    "" if (isinstance(value, float) and math.isnan(value)) or value is None else str(value)
                    for value in data[column.name].tolist()
                ]
                expected = [_cell_text(value) for value in column.values]
                for row, (left, right) in enumerate(zip(expected, actual)):
                    report["checked_cells"] += 1
                    if left != right:
                        report["value_mismatches"].append(
                            {"column": column.name, "row": row, "expected": left, "actual": right}
                        )
                report["checked_columns"] += 1
            _verify_dictionary(dictionary, result, report)
            report["notes"].append("XLSX 的 dictionary 工作表与 schema 逐列比对。")
        else:
            raise ValueError(f"不支持的核对格式：{fmt}")
    except Exception as exc:  # verification must report, not crash
        report["ok"] = False
        report["error"] = f"重新读取导出文件失败：{exc}"
        return report

    expected_columns = [column.name for column in result.columns]
    if actual_columns != expected_columns:
        report["column_mismatches"].append(
            {"expected": expected_columns, "actual": actual_columns}
        )
    report["ok"] = (
        not report["value_mismatches"]
        and not report["label_mismatches"]
        and not report["missing_mismatches"]
        and not report["column_mismatches"]
    )
    return report


def _verify_binary(frame: dict[str, Any], meta: Any, result: CompiledResult, report: dict[str, Any], fmt: str) -> None:
    labels_by_var = meta.variable_value_labels or {}
    missing_ranges = meta.missing_ranges or {}
    missing_user = meta.missing_user_values or {}
    for column in result.columns:
        if column.name not in frame:
            report["column_mismatches"].append({"column": column.name, "reason": "missing"})
            continue
        raw_values = list(frame[column.name])
        numeric_expected = _is_numeric(column)
        for row in range(result.row_count):
            report["checked_cells"] += 1
            expected_value = column.values[row]
            actual_value = raw_values[row] if row < len(raw_values) else None
            _compare_cell(
                report,
                column,
                row,
                expected_value,
                actual_value,
                numeric_expected,
                fmt,
            )
        report["checked_columns"] += 1
        _verify_labels(column, labels_by_var, report, fmt)
        _verify_missing(column, missing_ranges, missing_user, report, fmt)


def _compare_cell(
    report: dict[str, Any],
    column: CompiledColumn,
    row: int,
    expected: Any,
    actual: Any,
    numeric_expected: bool,
    fmt: str,
) -> None:
    if expected is None:
        if actual is None or (isinstance(actual, float) and math.isnan(actual)):
            return
        if isinstance(actual, str) and actual == "":
            return
        report["value_mismatches"].append(
            {"column": column.name, "row": row, "expected": None, "actual": repr(actual)}
        )
        return

    if numeric_expected and isinstance(expected, str) and expected.startswith("."):
        # Raw layer carrying a Stata extended missing code.  SPSS/CSV/XLSX can
        # only carry system missing; DTA is patched back to the code.
        if fmt == "dta":
            actual_code = actual if isinstance(actual, str) else None
            if actual_code is not None and not actual_code.startswith("."):
                actual_code = "." + actual_code
            if actual_code is None:
                actual_code = "."
            if actual_code != expected:
                report["value_mismatches"].append(
                    {"column": column.name, "row": row, "expected": expected, "actual": actual_code}
                )
        else:
            if not (
                actual is None
                or (isinstance(actual, float) and math.isnan(actual))
                or actual == ""
            ):
                report["value_mismatches"].append(
                    {
                        "column": column.name,
                        "row": row,
                        "expected": expected,
                        "actual": repr(actual),
                        "note": "目标格式只能表示系统缺失",
                    }
                )
        return

    if numeric_expected:
        left = _to_float(expected)
        right = _to_float(actual)
        if left is None and right is None:
            return
        if (
            left is None
            or right is None
            or not math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)
        ):
            report["value_mismatches"].append(
                {
                    "column": column.name,
                    "row": row,
                    "expected": expected,
                    "actual": raw_string(actual),
                }
            )
        return

    left_text = _cell_text(expected)
    right_text = _cell_text(actual)
    # SPSS writes SAV strings padded; DTA strings are exact.
    if fmt == "sav":
        right_text = right_text.rstrip()
        left_text = left_text.rstrip()
    if left_text != right_text:
        report["value_mismatches"].append(
            {
                "column": column.name,
                "row": row,
                "expected": left_text,
                "actual": right_text,
            }
        )


def _verify_labels(
    column: CompiledColumn, labels_by_var: dict[str, dict[Any, str]], report: dict[str, Any], fmt: str
) -> None:
    expected = {
        canonical_number(item["numeric"]): str(item["label"])
        for item in column.value_labels
        if item.get("numeric") is not None
    }
    actual = {
        canonical_number(key): str(value)
        for key, value in (labels_by_var.get(column.name) or {}).items()
        if not isinstance(key, str)
    }
    if expected and fmt in {"sav", "dta"}:
        if actual != expected:
            report["label_mismatches"].append(
                {
                    "column": column.name,
                    "expected": expected,
                    "actual": actual,
                }
            )
    elif not expected and actual:
        report["label_mismatches"].append(
            {"column": column.name, "expected": {}, "actual": actual}
        )


def _verify_missing(
    column: CompiledColumn,
    missing_ranges: dict[str, list[Any]],
    missing_user: dict[str, list[str]],
    report: dict[str, Any],
    fmt: str,
) -> None:
    """Only layers that can carry missing semantics are compared.

    Raw layers carry the source missing rules; analysis layers legitimately
    drop them (missing codes become blanks).  Comparing analysis layers would
    produce false alarms, so the report focuses on where meaning is stored.
    """

    if fmt == "sav" and column.layer == "raw":
        expected = _spss_missing_ranges(column)
        actual = missing_ranges.get(column.name) or []
        if expected and not _ranges_equal(expected, actual):
            report["missing_mismatches"].append(
                {"column": column.name, "expected": expected, "actual": actual}
            )
        elif not expected and actual:
            report["missing_mismatches"].append(
                {"column": column.name, "expected": [], "actual": actual}
            )
    elif fmt == "dta" and column.layer == "raw":
        expected_codes = sorted(
            {
                str(rule["code"])
                for rule in column.missing_rules
                if rule.get("kind") == "extended"
            }
        )
        actual_codes = sorted(
            "." + code if not code.startswith(".") else code
            for code in (missing_user.get(column.name) or [])
        )
        if expected_codes and actual_codes != expected_codes:
            report["missing_mismatches"].append(
                {"column": column.name, "expected": expected_codes, "actual": actual_codes}
            )


def _ranges_equal(expected: list[Any], actual: list[Any]) -> bool:
    def normalise(items: list[Any]) -> list[str]:
        out = []
        for item in items:
            if isinstance(item, dict):
                lo = canonical_number(item.get("lo"))
                hi = canonical_number(item.get("hi"))
                out.append(lo if lo == hi else f"{lo}..{hi}")
            elif isinstance(item, str):
                out.append(item)
            elif isinstance(item, (int, float)):
                out.append(canonical_number(item))
            else:
                out.append(str(item))
        return sorted(out)

    return normalise(expected) == normalise(actual)


def _verify_dictionary(dictionary: pd.DataFrame, result: CompiledResult, report: dict[str, Any]) -> None:
    rows = {row["列名"]: row for _, row in dictionary.iterrows()}
    for column in result.columns:
        row = rows.get(column.name)
        if row is None:
            report["column_mismatches"].append({"column": column.name, "reason": "dictionary missing"})
            continue
        expected_labels = "；".join(
            f"{item['value']}={item['label']}" for item in column.value_labels
        )
        if str(row.get("值标签", "")) != expected_labels:
            report["label_mismatches"].append(
                {
                    "column": column.name,
                    "expected": expected_labels,
                    "actual": str(row.get("值标签", "")),
                }
            )
        expected_rules = "；".join(
            f"{rule['kind']}:{rule.get('code') or (str(rule.get('low')) + '..' + str(rule.get('high')))}"
            for rule in column.missing_rules
            if rule.get("kind") != "system"
        )
        if str(row.get("缺失规则", "")) != expected_rules:
            report["missing_mismatches"].append(
                {
                    "column": column.name,
                    "expected": expected_rules,
                    "actual": str(row.get("缺失规则", "")),
                }
            )
