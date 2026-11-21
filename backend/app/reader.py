"""Read SPSS SAV / Stata DTA files into the intake's layered model.

Every cell keeps three layers plus a state:

* ``raw``      what the file stores (number, string, or ``.a`` style code)
* ``label``    what the software would display (value label, formatted date)
* ``analysis`` the value an analysis should use (missing -> null)

Missing semantics are kept in ``state``/``rule``; see :mod:`app.missing`.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import pyreadstat

from .missing import MissingRule, build_rules, system_rule
from .timecodes import TimeSpec, interpret_value, parse_time_spec
from .values import canonical_number, json_scalar, number_key

NUMERIC_STORAGE = {"double", "float", "int8", "int16", "int32", "int64"}
SYSTEM_STATE = "system_missing"
USER_STATE = "user_missing"
EXT_STATE = "extended_missing"
VALID_STATE = "valid"
UNSUPPORTED_STATE = "unsupported"
INVALID_STATE = "invalid"


@dataclass
class Variable:
    name: str
    index: int
    label: Optional[str]
    storage_type: str
    storage_width: Optional[int]
    display_width: Optional[int]
    source_format: Optional[str]
    format_base: Optional[str]
    measure: Optional[str]
    encoding: Optional[str]
    value_labels: list[dict[str, Any]] = field(default_factory=list)
    value_labels_by_key: dict[str, str] = field(default_factory=dict)
    rules: list[MissingRule] = field(default_factory=list)
    time: Optional[TimeSpec] = None
    classification: str = "numeric"
    notes: list[str] = field(default_factory=list)
    is_strl: bool = False
    observed_max_bytes: int = 0
    observed_max_chars: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "index": self.index,
            "label": self.label,
            "storage_type": self.storage_type,
            "storage_width": self.storage_width,
            "display_width": self.display_width,
            "source_format": self.source_format,
            "format_base": self.format_base,
            "measure": self.measure,
            "encoding": self.encoding,
            "value_labels": self.value_labels,
            "missing_rules": [rule.to_dict() for rule in self.rules],
            "time": self.time.to_dict() if self.time else None,
            "classification": self.classification,
            "notes": self.notes,
            "is_strl": self.is_strl,
            "observed_max_bytes": self.observed_max_bytes,
            "observed_max_chars": self.observed_max_chars,
        }


@dataclass
class ReadResult:
    file_type: str
    row_count: int
    column_count: int
    encoding: Optional[str]
    file_label: Optional[str]
    file_format: str
    variables: list[Variable]
    columns: dict[str, dict[str, list[Any]]]
    notes: list[str]
    label_conflicts: list[dict[str, Any]]

    def counts(self, name: str) -> dict[str, int]:
        states = self.columns[name]["state"]
        result = {
            VALID_STATE: 0,
            SYSTEM_STATE: 0,
            USER_STATE: 0,
            EXT_STATE: 0,
            UNSUPPORTED_STATE: 0,
            INVALID_STATE: 0,
        }
        for state in states:
            result[state] = result.get(state, 0) + 1
        return result

    def to_metadata(self) -> dict[str, Any]:
        variables = []
        for variable in self.variables:
            data = variable.to_dict()
            data["counts"] = self.counts(variable.name)
            data["sample_cells"] = self.sample_cells(variable.name, 8)
            variables.append(data)
        return {
            "file_type": self.file_type,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "encoding": self.encoding,
            "file_label": self.file_label,
            "file_format": self.file_format,
            "variables": variables,
            "notes": self.notes,
            "label_conflicts": self.label_conflicts,
        }

    def sample_cells(self, name: str, limit: int) -> list[dict[str, Any]]:
        column = self.columns[name]
        out = []
        for row in range(min(limit, self.row_count)):
            out.append(
                {
                    "row": row,
                    "raw": column["raw"][row],
                    "label": column["label"][row],
                    "analysis": column["analysis"][row],
                    "state": column["state"][row],
                    "rule": column["rule"][row],
                    "ext_code": column["ext_code"][row],
                }
            )
        return out


class UnsupportedFileError(ValueError):
    pass


def detect_file_type(filename: str, head: bytes) -> str:
    lower = filename.lower()
    if head.startswith(b"$FL2") or head.startswith(b"$FL3"):
        return "sav"
    if head.startswith(b"<stata_dta>"):
        return "dta"
    if lower.endswith(".sav"):
        if head.startswith(b"<stata_dta>"):
            raise UnsupportedFileError("扩展名是 .sav，但文件内容是 Stata DTA")
        raise UnsupportedFileError("文件扩展名为 .sav，但缺少 SPSS 文件头（$FL2/$FL3）")
    if lower.endswith(".dta"):
        raise UnsupportedFileError("文件扩展名为 .dta，但缺少 Stata 文件头 <stata_dta>")
    raise UnsupportedFileError("仅支持 SPSS .sav 与 Stata .dta 文件")


def _format_base(fmt: Optional[str]) -> Optional[str]:
    if not fmt:
        return None
    raw = fmt.strip()
    if raw.startswith("%"):
        body = raw[1:]
        m = re.match(r"^-?\d*(?:\.\d+)?(.*)$", body)
        body = m.group(1) if m else body
        for token in ("tC", "tc", "td", "tm", "tq", "th", "tw", "ty", "tb", "tg"):
            if body.startswith(token):
                return "%" + token
        return "%" + body if body else raw
    m = re.match(r"^([A-Za-z]+)", raw)
    return m.group(1).upper() if m else raw


def _normalised_time(raw_value: Any, ext_code: Optional[str], spec: TimeSpec) -> Any:
    if ext_code:
        return None
    return interpret_value(raw_value, spec)


def _value_label_map(raw_labels: dict[Any, str]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    items: list[dict[str, Any]] = []
    by_key: dict[str, str] = {}
    for value, text in (raw_labels or {}).items():
        key = number_key(value)
        if key is None:
            key = str(value)
        by_key[key] = text
        numeric: Optional[float]
        if isinstance(value, str):
            numeric = None
        else:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                numeric = None
        items.append({"value": key, "numeric": numeric, "label": text})
    items.sort(key=lambda item: (item["numeric"] is None, item["numeric"] or 0, item["value"]))
    return items, by_key


def _find_label(key: Optional[str], by_key: dict[str, str]) -> Optional[str]:
    if key is None:
        return None
    return by_key.get(key)


def _numeric_summary(values: list[Any]) -> dict[str, Any]:
    numbers = []
    zeros = 0
    for value in values:
        if value is None or isinstance(value, str):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        numbers.append(number)
        if number == 0:
            zeros += 1
    if not numbers:
        return {"n": 0, "mean": None, "std": None, "min": None, "max": None, "zeros": 0}
    mean = sum(numbers) / len(numbers)
    variance = sum((item - mean) ** 2 for item in numbers) / len(numbers)
    return {
        "n": len(numbers),
        "mean": mean,
        "std": math.sqrt(variance),
        "min": min(numbers),
        "max": max(numbers),
        "zeros": zeros,
    }


def read_file(path: str, filename: str, encoding: Optional[str] = None) -> ReadResult:
    with open(path, "rb") as handle:
        head = handle.read(32)
    file_type = detect_file_type(filename, head)

    try:
        if file_type == "sav":
            frame, meta = pyreadstat.read_sav(
                path,
                user_missing=True,
                disable_datetime_conversion=True,
                output_format="dict",
                encoding=encoding,
            )
        else:
            frame, meta = pyreadstat.read_dta(
                path,
                user_missing=True,
                disable_datetime_conversion=True,
                output_format="dict",
                encoding=encoding,
            )
    except Exception as exc:  # pyreadstat raises its own error types
        raise UnsupportedFileError(f"无法读取 {filename}：{exc}") from exc

    names = list(meta.column_names or list(frame.keys()))
    row_count = int(meta.number_rows or 0)
    encoding_final = meta.file_encoding or ("UTF-8" if file_type == "dta" else None)

    readstat_types = meta.readstat_variable_types or {}
    storage_widths = meta.variable_storage_width or {}
    display_widths = meta.variable_display_width or {}
    formats = meta.original_variable_types or {}
    measures = meta.variable_measure or {}
    variable_labels = meta.column_names_to_labels or {}
    value_labels_map = meta.variable_value_labels or {}
    missing_ranges_map = meta.missing_ranges or {}
    missing_user_map = meta.missing_user_values or {}

    variables: list[Variable] = []
    columns: dict[str, dict[str, list[Any]]] = {}
    notes: list[str] = []
    ext_codes_seen: dict[str, set[str]] = {}

    for index, name in enumerate(names):
        storage_type = str(readstat_types.get(name, "double"))
        is_string = storage_type == "string"
        width = storage_widths.get(name)
        display = display_widths.get(name)
        fmt = formats.get(name)
        raw_labels = value_labels_map.get(name) or {}
        labels_list, labels_by_key = _value_label_map(raw_labels)

        rules = build_rules(
            variable=name,
            file_type=file_type,
            storage_type=storage_type,
            value_labels=raw_labels,
            missing_ranges=missing_ranges_map.get(name),
            missing_user_values=missing_user_map.get(name),
        )

        spec: Optional[TimeSpec] = None
        classification = "string" if is_string else "numeric"
        variable_notes: list[str] = []
        if not is_string:
            spec = parse_time_spec(fmt, storage_type)
            if spec is not None:
                if spec.supported:
                    classification = spec.kind
                else:
                    classification = "unsupported"
                variable_notes.extend(spec.notes)
                if spec.reason:
                    variable_notes.append(spec.reason)

        is_strl = bool(is_string and (width in (None, 0) or int(width) == 0))
        if is_string:
            encoding_text = encoding_final or "未知"
            if is_strl:
                variable_notes.append(
                    "Stata strL 长字符串按 8 字节引用存储；实际内容长度见“观测最大字节数”，"
                    "显示宽度在 Stata 中无定义（-9）。"
                )
            else:
                variable_notes.append(
                    f"字符串按 {encoding_text} 解码；存储宽度 {width} 字节，"
                    f"显示宽度 {display if display is not None and int(display) >= 0 else '未定义'}"
                    "（字符宽度），两者分开记录。"
                )
            if any(rule.value_kind == "string" for rule in rules):
                variable_notes.append("字符串用户缺失码与空字符串系统缺失分开标记。")

        for rule in rules:
            if rule.kind == "user":
                variable_notes.append(f"用户定义缺失：{rule.description}")
            elif rule.kind == "extended":
                variable_notes.append(f"扩展缺失码 {rule.code}（Stata 专用，与系统缺失 . 不同）")

        variable = Variable(
            name=name,
            index=index,
            label=variable_labels.get(name),
            storage_type=storage_type,
            storage_width=int(width) if width is not None else None,
            display_width=int(display) if display is not None and int(display) >= 0 else None,
            source_format=fmt,
            format_base=_format_base(fmt),
            measure=measures.get(name),
            encoding=encoding_final if is_string else None,
            value_labels=labels_list,
            value_labels_by_key=labels_by_key,
            rules=rules,
            time=spec,
            classification=classification,
            notes=variable_notes,
            is_strl=is_strl,
        )

        raw_values = list(frame.get(name, []))
        if len(raw_values) < row_count:
            raw_values.extend([None] * (row_count - len(raw_values)))

        raw_column: list[Any] = []
        label_column: list[Any] = []
        analysis_column: list[Any] = []
        state_column: list[str] = []
        rule_column: list[Optional[str]] = []
        ext_column: list[Optional[str]] = []
        max_bytes = 0
        max_chars = 0

        ext_here: set[str] = set()

        for row_index, value in enumerate(raw_values):
            value = json_scalar(value)
            ext_code: Optional[str] = None

            if not is_string and isinstance(value, str):
                letter = value[1:] if value.startswith(".") else value
                if len(letter) == 1 and letter.lower() in "abcdefghijklmnopqrstuvwxyz":
                    ext_code = "." + letter.lower()
                elif value == ".":
                    ext_code = "."

            if ext_code and ext_code != ".":
                ext_here.add(ext_code)

            # Match missing rules before interpreting anything.
            matched_rule: Optional[MissingRule] = None
            if ext_code and ext_code != ".":
                for rule in rules:
                    if rule.kind == "extended" and rule.code == ext_code:
                        matched_rule = rule
                        break
                if matched_rule is None:
                    matched_rule = MissingRule(
                        id=f"extended:{name}:{ext_code}",
                        kind="extended",
                        code=ext_code,
                        source="Stata 扩展缺失码",
                        description=f"Stata 扩展缺失码 {ext_code}",
                    )
                    rules.append(matched_rule)
            else:
                if is_string:
                    if value is None or value == "":
                        matched_rule = system_rule()
                    else:
                        for rule in rules:
                            if rule.kind == "user" and rule.matches(value):
                                matched_rule = rule
                                break
                else:
                    if value is None or (isinstance(value, float) and math.isnan(value)):
                        matched_rule = system_rule()
                    else:
                        for rule in rules:
                            if rule.kind == "user" and rule.matches(value):
                                matched_rule = rule
                                break

            raw_out: Any
            if ext_code:
                raw_out = ext_code
            else:
                raw_out = value

            if is_string and isinstance(value, str):
                max_chars = max(max_chars, len(value))
                try:
                    max_bytes = max(max_bytes, len(value.encode(encoding_final or "utf-8")))
                except (LookupError, UnicodeEncodeError):
                    max_bytes = max(max_bytes, len(value.encode("utf-8", errors="replace")))

            # System missing.
            if matched_rule is not None and matched_rule.kind == "system":
                raw_column.append(raw_out)
                label_column.append(None)
                analysis_column.append(None)
                state_column.append(SYSTEM_STATE)
                rule_column.append("system")
                ext_column.append(None)
                continue

            # Stata extended missing.
            if ext_code and ext_code != ".":
                raw_column.append(raw_out)
                # Stata displays extended missing codes literally (".a").
                label_column.append(ext_code)
                analysis_column.append(None)
                state_column.append(EXT_STATE)
                rule_column.append(matched_rule.id if matched_rule else None)
                ext_column.append(ext_code)
                continue

            # SPSS user-defined / Stata-labelled missing codes.
            if matched_rule is not None and matched_rule.kind in {"user", "extended"}:
                key = number_key(value) if not isinstance(value, str) else value
                label_value = matched_rule.label or _find_label(key, labels_by_key)
                if label_value is None and isinstance(value, str):
                    label_value = value
                raw_column.append(raw_out)
                label_column.append(label_value)
                analysis_column.append(None)
                state_column.append(USER_STATE)
                rule_column.append(matched_rule.id)
                ext_column.append(ext_code)
                continue

            # Valid value.
            if spec is not None:
                interpreted = _normalised_time(value, ext_code, spec)
                if interpreted.analysis_state == "unsupported":
                    raw_column.append(raw_out)
                    label_column.append(None)
                    analysis_column.append(None)
                    state_column.append(UNSUPPORTED_STATE)
                    rule_column.append("unsupported")
                    ext_column.append(None)
                    continue
                if interpreted.analysis_state != "ok":
                    raw_column.append(raw_out)
                    label_column.append(None)
                    analysis_column.append(None)
                    state_column.append(INVALID_STATE)
                    rule_column.append(interpreted.analysis_state)
                    ext_column.append(None)
                    if interpreted.notes:
                        for note in interpreted.notes:
                            if note not in variable_notes:
                                variable_notes.append(note)
                    continue
                key = number_key(value)
                label_value = _find_label(key, labels_by_key)
                if label_value is None:
                    label_value = interpreted.label
                raw_column.append(raw_out)
                label_column.append(label_value)
                analysis_column.append(interpreted.analysis)
                state_column.append(VALID_STATE)
                rule_column.append(None)
                ext_column.append(None)
                if interpreted.notes:
                    for note in interpreted.notes:
                        if note not in variable_notes:
                            variable_notes.append(note)
                continue

            if is_string:
                label_value = value
                raw_column.append(raw_out)
                label_column.append(label_value)
                analysis_column.append(value)
                state_column.append(VALID_STATE)
                rule_column.append(None)
            else:
                key = number_key(value)
                label_value = _find_label(key, labels_by_key)
                if label_value is None:
                    label_value = canonical_number(value) if value is not None else None
                raw_column.append(raw_out)
                label_column.append(label_value)
                analysis_column.append(float(value) if value is not None else None)
                state_column.append(VALID_STATE)
                rule_column.append(None)
            ext_column.append(None)

        variable.observed_max_bytes = max_bytes
        variable.observed_max_chars = max_chars

        if is_string and encoding_final:
            variable.notes.append(
                f"观测最大长度：{max_chars} 字符 / {max_bytes} 字节（按 {encoding_final} 编码）。"
            )
        if file_type == "dta" and ext_here:
            variable.notes.append(
                "检测到扩展缺失码：" + "、".join(sorted(ext_here)) + "；它们与基础缺失 . 含义不同。"
            )

        variables.append(variable)
        columns[name] = {
            "raw": raw_column,
            "label": label_column,
            "analysis": analysis_column,
            "state": state_column,
            "rule": rule_column,
            "ext_code": ext_column,
            "summary": _numeric_summary(analysis_column),
        }
        if ext_here:
            ext_codes_seen[name] = ext_here

    # Dataset-level notes.
    if file_type == "sav":
        notes.append(
            "SPSS：空数值/空字符串记为系统缺失；用户定义缺失按每个变量自己的缺失规则解释，"
            "不与其他变量共享。"
        )
    else:
        notes.append(
            "Stata：基础缺失 . 记为系统缺失；扩展缺失 .a–.z 单独保留编码，不能与 . 或有效值合并。"
        )
    notes.append(
        f"字符串按 {encoding_final or '未知'} 解码；存储宽度（字节）与显示宽度（字符）分别记录，"
        "导出时会保留该区分说明。"
    )
    if any(variable.time and variable.time.supported for variable in variables):
        notes.append(
            "日期/时间按源格式的起点与单位换算：SPSS 以 1582-10-14 为秒零点，"
            "Stata 以 1960-01-01 为起点（%td 天、%tc 毫秒）。"
        )
    if any(variable.classification == "unsupported" for variable in variables):
        notes.append(
            "存在不支持的时间格式：保留原始数值并标记为 unsupported，不按普通数字当作有效值。"
        )

    label_conflicts = _label_conflicts(variables)

    return ReadResult(
        file_type=file_type,
        row_count=row_count,
        column_count=len(names),
        encoding=encoding_final,
        file_label=meta.file_label,
        file_format=_file_format_string(path, file_type),
        variables=variables,
        columns=columns,
        notes=notes,
        label_conflicts=label_conflicts,
    )


def _label_conflicts(variables: list[Variable]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, list[str]]] = {}
    for variable in variables:
        for item in variable.value_labels:
            key = str(item["value"])
            seen.setdefault(key, {}).setdefault(item["label"], []).append(variable.name)
    conflicts = []
    for key, labels in sorted(seen.items()):
        if len(labels) > 1:
            conflicts.append(
                {
                    "value": key,
                    "meanings": [
                        {"label": label, "variables": names}
                        for label, names in sorted(labels.items())
                    ],
                }
            )
    return conflicts


def _file_format_string(path: str, file_type: str) -> str:
    try:
        with open(path, "rb") as handle:
            head = handle.read(300)
    except OSError:
        return file_type
    if file_type == "dta":
        match = re.search(rb"<release>(\d+)</release>", head)
        if match:
            return f"Stata DTA {match.group(1).decode()}"
        return "Stata DTA"
    if head.startswith(b"$FL3"):
        return "SPSS SAV (zsav/$FL3)"
    if head.startswith(b"$FL2"):
        return "SPSS SAV ($FL2)"
    return "SPSS SAV"


def file_summary(path: str) -> dict[str, Any]:
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        head = handle.read(32)
    return {"size_bytes": size, "file_type": detect_file_type(os.path.basename(path), head)}
