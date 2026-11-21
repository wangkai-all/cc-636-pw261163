"""Compile a layered interpretation into an explicit, queryable result.

The compiler never mutates the interpretation.  It reads it, applies the
caller's field selection and missing-code conversions, and produces a new
column set.  Every conversion is recorded in the schema and in the manifest so
a result can be audited later.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Optional

from .reader import (
    EXT_STATE,
    INVALID_STATE,
    SYSTEM_STATE,
    UNSUPPORTED_STATE,
    USER_STATE,
    VALID_STATE,
    ReadResult,
)
from .timecodes import TimeSpec, interpret_value
from .values import canonical_number, json_scalar, number_key

LAYERS = ("raw", "label", "analysis", "state")
LAYER_TITLES = {
    "raw": "原始值",
    "label": "显示标签",
    "analysis": "分析值",
    "state": "缺失/有效性",
}
ACTIONS = {"valid", "set", "system", "missing"}
STATE_TEXT = {
    VALID_STATE: "valid",
    SYSTEM_STATE: "missing_system",
    USER_STATE: "missing_user",
    EXT_STATE: "missing_extended",
    UNSUPPORTED_STATE: "unsupported",
    INVALID_STATE: "invalid",
}

PREVIEW_ROW_LIMIT = 50


class SpecError(ValueError):
    pass


@dataclass
class Override:
    rule_id: str
    action: str
    value: Any = None
    label: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "action": self.action,
            "value": json_scalar(self.value),
            "label": self.label,
        }


@dataclass
class FieldSpec:
    name: str
    layers: list[str]
    overrides: list[Override] = field(default_factory=list)
    time_mode: str = "interpret"  # interpret | numeric

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "layers": self.layers,
            "overrides": [item.to_dict() for item in self.overrides],
            "time_mode": self.time_mode,
        }


@dataclass
class CompiledColumn:
    name: str
    source: str
    layer: str
    dtype: str  # number | string
    title: str
    description: str
    value_labels: list[dict[str, Any]] = field(default_factory=list)
    missing_rules: list[dict[str, Any]] = field(default_factory=list)
    time: Optional[dict[str, Any]] = None
    notes: list[str] = field(default_factory=list)
    values: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "layer": self.layer,
            "dtype": self.dtype,
            "title": self.title,
            "description": self.description,
            "value_labels": self.value_labels,
            "missing_rules": self.missing_rules,
            "time": self.time,
            "notes": self.notes,
        }


@dataclass
class CompiledResult:
    columns: list[CompiledColumn]
    row_count: int
    overrides_applied: list[dict[str, Any]]
    notes: list[str]

    @property
    def schema(self) -> list[dict[str, Any]]:
        return [column.to_dict() for column in self.columns]

    def to_rows(self, limit: int, offset: int) -> list[dict[str, Any]]:
        rows = []
        for index in range(offset, min(offset + limit, self.row_count)):
            row = {"row_id": index}
            for column in self.columns:
                row[column.name] = column.values[index]
            rows.append(row)
        return rows


def canonical_spec(payload: dict[str, Any]) -> dict[str, Any]:
    fields = []
    for item in payload.get("fields", []):
        fields.append(
            {
                "name": item["name"],
                "layers": sorted(set(item.get("layers", list(LAYERS)))),
                "time_mode": item.get("time_mode", "interpret"),
                "overrides": sorted(
                    (
                        {
                            "rule_id": override["rule_id"],
                            "action": override["action"],
                            "value": override.get("value"),
                            "label": override.get("label"),
                        }
                        for override in item.get("overrides", [])
                    ),
                    key=lambda entry: (entry["rule_id"], entry["action"]),
                ),
            }
        )
    return {"fields": fields}


def spec_token(upload_sha256: str, payload: dict[str, Any]) -> str:
    canonical = canonical_spec(payload)
    text = json.dumps({"upload": upload_sha256, "spec": canonical}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def parse_spec(read: ReadResult, payload: dict[str, Any]) -> list[FieldSpec]:
    variables = {variable.name: variable for variable in read.variables}
    raw_fields = payload.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise SpecError("至少选择一个字段")
    seen: set[str] = set()
    fields: list[FieldSpec] = []
    for item in raw_fields:
        if not isinstance(item, dict) or "name" not in item:
            raise SpecError("字段定义缺少 name")
        name = str(item["name"])
        if name not in variables:
            raise SpecError(f"未知字段：{name}")
        if name in seen:
            raise SpecError(f"字段重复：{name}")
        seen.add(name)
        layers = item.get("layers")
        if layers is None:
            layers = list(LAYERS)
        if not isinstance(layers, list):
            raise SpecError(f"字段 {name} 的 layers 必须是数组")
        layers = [str(layer) for layer in layers]
        unknown = [layer for layer in layers if layer not in LAYERS]
        if unknown:
            raise SpecError(f"字段 {name} 使用了未知的层：{', '.join(unknown)}")
        if not layers:
            raise SpecError(f"字段 {name} 至少要保留一层")
        time_mode = item.get("time_mode", "interpret")
        if time_mode not in {"interpret", "numeric"}:
            raise SpecError(f"字段 {name} 的 time_mode 只能是 interpret 或 numeric")
        variable = variables[name]
        if time_mode == "numeric" and variable.time is None:
            raise SpecError(f"字段 {name} 不是日期/时间字段，不能选择保留原始数值")
        overrides: list[Override] = []
        # ``system`` is not a metadata rule but a real addressable state: blank
        # cells can be given an explicit value for a what-if run.
        rule_ids = {rule.id for rule in variable.rules} | {"system"}
        for override_data in item.get("overrides", []) or []:
            if not isinstance(override_data, dict) or "rule_id" not in override_data:
                raise SpecError(f"字段 {name} 的缺失转换缺少 rule_id")
            rule_id = str(override_data["rule_id"])
            action = str(override_data.get("action", "missing"))
            if rule_id not in rule_ids:
                raise SpecError(f"字段 {name} 没有规则 {rule_id}")
            if action not in ACTIONS:
                raise SpecError(f"字段 {name} 的转换动作 {action} 不受支持")
            value = override_data.get("value")
            if action == "set" and (value is None or value == ""):
                raise SpecError(f"字段 {name} 的规则 {rule_id} 选择了 set，但没有提供值")
            overrides.append(
                Override(
                    rule_id=rule_id,
                    action=action,
                    value=json_scalar(value),
                    label=override_data.get("label"),
                )
            )
        fields.append(FieldSpec(name=name, layers=layers, overrides=overrides, time_mode=time_mode))
    return fields



def _rule_matches_at(
    read: ReadResult, name: str, rule_id: str, row: int
) -> bool:
    column = read.columns[name]
    if rule_id == "system":
        return column["state"][row] == SYSTEM_STATE
    return column["rule"][row] == rule_id


def _affected_rows(read: ReadResult, spec: FieldSpec) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for override in spec.overrides:
        rows = [
            row
            for row in range(read.row_count)
            if _rule_matches_at(read, spec.name, override.rule_id, row)
        ]
        if rows:
            result[override.rule_id] = rows
    return result


def _validate_override_value(variable: Any, override: Override) -> None:
    if override.action == "set":
        if variable.time is not None:
            from .timecodes import _parse_iso  # local import to avoid cycle at module load

            try:
                _parse_iso(str(override.value))
            except ValueError as exc:
                raise SpecError(
                    f"字段 {variable.name} 的日期/时间试算值无法解析：{exc}"
                ) from exc
            return
        if variable.classification == "string":
            if not isinstance(override.value, str):
                raise SpecError(f"字段 {variable.name} 是字符串，试算值必须是文本")
            return
        try:
            float(override.value)
        except (TypeError, ValueError) as exc:
            raise SpecError(
                f"字段 {variable.name} 是数值字段，试算值必须是数字"
            ) from exc


def _display_for_time(value: Any, spec: TimeSpec) -> tuple[Any, Any]:
    interpreted = interpret_value(value, spec)
    if interpreted.analysis_state != "ok":
        return None, None
    return interpreted.label, interpreted.analysis


def _label_for_code(variable: Any, value: Any) -> Optional[str]:
    key = number_key(value) if not isinstance(value, str) else value
    if key is None:
        return None
    return variable.value_labels_by_key.get(key)


def _analysis_for_override(
    variable: Any,
    override: Override,
    raw_value: Any,
    ext_code: Optional[str],
) -> tuple[Any, Optional[str], Optional[str]]:
    """Return (analysis, label, note) for a row affected by an override."""

    if override.action == "missing":
        return None, None, None
    if override.action == "system":
        return None, None, "按用户选择转换为系统缺失（原缺失码保留在 raw/state 中）"

    if variable.time is not None and variable.classification not in {"unsupported"}:
        # Time fields are interpreted through their own format/epoch.
        if override.action == "valid":
            if ext_code:
                return None, None, "扩展缺失码没有可用的原始数值，需提供明确日期"
            label, analysis = _display_for_time(raw_value, variable.time)
            return analysis, label, "按源格式恢复为有效日期/时间"
        target = override.value
        if variable.time.kind in {"date", "datetime"}:
            from .timecodes import _parse_iso

            dt = _parse_iso(str(target))
            if variable.time.kind == "date":
                analysis = dt.date().isoformat()
                label = analysis
            else:
                analysis = dt.strftime("%Y-%m-%dT%H:%M:%S")
                label = dt.strftime("%Y-%m-%d %H:%M:%S")
            return analysis, override.label or label, "按用户提供的日期/时间试算"
        if variable.time.kind in {"duration", "year"}:
            try:
                number = float(target)
            except (TypeError, ValueError) as exc:
                raise SpecError(f"字段 {variable.name} 需要数字试算值") from exc
            if variable.time.kind == "year" and not float(number).is_integer():
                raise SpecError(f"字段 {variable.name} 的年份试算值必须是整数")
            return number, override.label or canonical_number(number), "按用户提供的数值试算"
        # month/quarter/half-year take an ISO date and map to their period start.
        from .timecodes import analysis_to_raw

        number, _ = analysis_to_raw(str(target), variable.time)
        interpreted = interpret_value(number, variable.time)
        if interpreted.analysis_state != "ok":
            raise SpecError(f"字段 {variable.name} 的周期试算值无法换算")
        return interpreted.analysis, override.label or interpreted.label, "按用户提供的日期试算周期"

    if override.action == "valid":
        value = raw_value
        if ext_code:
            return None, None, "扩展缺失码没有可用的原始数值，需提供明确值"
        if variable.classification == "string":
            return value, _label_for_code(variable, value) or value, "按用户选择把该缺失码恢复为有效文本"
        if value is None:
            return None, None, "系统缺失没有可恢复的原始值，需提供明确值"
        return float(value), _label_for_code(variable, value), "按用户选择把该缺失码恢复为有效值"

    target = override.value
    if variable.classification == "string":
        return str(target), override.label or str(target), "按用户提供的文本试算"
    try:
        number = float(target)
    except (TypeError, ValueError) as exc:
        raise SpecError(f"字段 {variable.name} 需要数字试算值") from exc
    return number, override.label or _label_for_code(variable, number) or canonical_number(number), "按用户提供的数值试算"



def compile_result(read: ReadResult, fields: list[FieldSpec]) -> CompiledResult:
    variables = {variable.name: variable for variable in read.variables}
    columns: list[CompiledColumn] = []
    overrides_applied: list[dict[str, Any]] = []
    notes: list[str] = []

    for spec in fields:
        variable = variables[spec.name]
        column = read.columns[spec.name]
        override_by_rule = {override.rule_id: override for override in spec.overrides}
        affected = _affected_rows(read, spec)
        for override in spec.overrides:
            _validate_override_value(variable, override)
            rows = affected.get(override.rule_id, [])
            if not rows:
                notes.append(
                    f"字段 {variable.name} 的规则 {override.rule_id} 没有命中任何行，转换未生效。"
                )
            overrides_applied.append(
                {
                    "field": variable.name,
                    "rule_id": override.rule_id,
                    "action": override.action,
                    "value": json_scalar(override.value),
                    "label": override.label,
                    "affected_rows": rows,
                    "affected_count": len(rows),
                }
            )

        if "raw" in spec.layers:
            raw_values = list(column["ext_code"])
            raw_values = [
                column["raw"][row] if column["ext_code"][row] is None else column["ext_code"][row]
                for row in range(read.row_count)
            ]
            raw_dtype = "string" if variable.storage_type == "string" else "number"
            raw_labels = variable.value_labels if raw_dtype == "number" else []
            columns.append(
                CompiledColumn(
                    name=f"{variable.name}__raw",
                    source=variable.name,
                    layer="raw",
                    dtype=raw_dtype,
                    title=f"{variable.label or variable.name} · 原始值",
                    description=(
                        "按文件存储的意义原样保留：SPSS 用户缺失码仍是存储值，"
                        "Stata 扩展缺失码以 .a-.z 文本保留。"
                    ),
                    value_labels=raw_labels,
                    missing_rules=[rule.to_dict() for rule in variable.rules],
                    time=variable.time.to_dict() if variable.time else None,
                    notes=[f"源存储类型：{variable.storage_type}"],
                    values=raw_values,
                )
            )

        if "label" in spec.layers:
            label_values: list[Any] = []
            for row in range(read.row_count):
                override = override_by_rule.get(column["rule"][row] or "")
                ext_code = column["ext_code"][row]
                if override is not None and override.action in {"valid", "set"}:
                    _, label, _ = _analysis_for_override(
                        variable, override, column["raw"][row], ext_code
                    )
                    label_values.append(label)
                    continue
                if override is not None and override.action == "system":
                    label_values.append(None)
                    continue
                if variable.time is not None and spec.time_mode == "numeric":
                    label_values.append(column["raw"][row])
                    continue
                label_values.append(column["label"][row])
            columns.append(
                CompiledColumn(
                    name=f"{variable.name}__label",
                    source=variable.name,
                    layer="label",
                    dtype="string",
                    title=f"{variable.label or variable.name} · 显示标签",
                    description="按源文件的值标签/日期格式得到的人类可读文本；缺失码显示其标签或留空。",
                    notes=[
                        "标签文本不参与数值分析；同一数字在不同字段的标签可能不同。"
                    ],
                    values=label_values,
                )
            )

        if "analysis" in spec.layers:
            analysis_values: list[Any] = []
            analysis_labels: list[dict[str, Any]] = []
            analysis_dtype = "string" if variable.storage_type == "string" else "number"
            if (
                variable.time is not None
                and spec.time_mode == "interpret"
                and variable.time.kind != "duration"
            ):
                # Calendar interpretations are ISO text; durations stay numeric
                # seconds so they can still be analysed as numbers.
                analysis_dtype = "string"
            valid_codes: set[str] = set()
            for row in range(read.row_count):
                state = column["state"][row]
                ext_code = column["ext_code"][row]
                override = override_by_rule.get(column["rule"][row] or "")
                if state == UNSUPPORTED_STATE:
                    analysis_values.append(None)
                    continue
                if override is not None:
                    if override.action == "valid":
                        value = _analysis_for_override(
                            variable, override, column["raw"][row], ext_code
                        )[0]
                    elif override.action == "set":
                        value = _analysis_for_override(
                            variable, override, column["raw"][row], ext_code
                        )[0]
                    else:
                        value = None
                    analysis_values.append(value)
                    continue
                if state in {SYSTEM_STATE, USER_STATE, EXT_STATE, INVALID_STATE}:
                    analysis_values.append(None)
                    continue
                if variable.time is not None:
                    if spec.time_mode == "numeric":
                        analysis_values.append(float(column["raw"][row]))
                    else:
                        analysis_values.append(column["analysis"][row])
                else:
                    value = column["analysis"][row]
                    analysis_values.append(value)
                    if variable.storage_type != "string" and value is not None:
                        valid_codes.add(canonical_number(value))
            if variable.storage_type != "string":
                analysis_labels = [
                    item
                    for item in variable.value_labels
                    if str(item["value"]) in valid_codes
                ]
            columns.append(
                CompiledColumn(
                    name=f"{variable.name}__analysis",
                    source=variable.name,
                    layer="analysis",
                    dtype=analysis_dtype,
                    title=f"{variable.label or variable.name} · 分析值",
                    description=(
                        "供分析使用的值：缺失一律为空；日期/时间按源格式的起点解释为 ISO 值；"
                        "不支持的格式为空并在 state 中标记。"
                    ),
                    value_labels=analysis_labels,
                    missing_rules=[rule.to_dict() for rule in variable.rules],
                    time=variable.time.to_dict() if variable.time else None,
                    notes=[
                        "分析值不使用缺失码本身；若要把缺失码改为有效值，请在试算中显式转换。",
                    ],
                    values=analysis_values,
                )
            )

        if "state" in spec.layers:
            state_values: list[str] = []
            for row in range(read.row_count):
                state = column["state"][row]
                ext_code = column["ext_code"][row]
                text = STATE_TEXT.get(state, state)
                if ext_code:
                    text = f"{text}:{ext_code}"
                override = override_by_rule.get(column["rule"][row] or "")
                if override is not None:
                    if override.action == "set":
                        text = f"{text}->set"
                    elif override.action == "valid":
                        text = f"{text}->valid"
                    elif override.action == "system":
                        text = f"{text}->system"
                state_values.append(text)
            columns.append(
                CompiledColumn(
                    name=f"{variable.name}__state",
                    source=variable.name,
                    layer="state",
                    dtype="string",
                    title=f"{variable.label or variable.name} · 缺失/有效性",
                    description=(
                        "系统缺失、用户定义缺失、Stata 扩展缺失码（含 .a-.z）分开标记；"
                        "->set/->valid 表示该行应用了试算转换。"
                    ),
                    notes=["导出后可用该列核对缺失含义是否保持一致。"],
                    values=state_values,
                )
            )

        if variable.classification == "unsupported":
            notes.append(
                f"字段 {variable.name} 使用不支持的格式 {variable.source_format}："
                "分析值一律为空，state 标记 unsupported，原始数值保留在 raw。"
            )

    return CompiledResult(
        columns=columns,
        row_count=read.row_count,
        overrides_applied=overrides_applied,
        notes=notes,
    )


def _numeric(values: list[Any]) -> list[float]:
    out = []
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            out.append(number)
    return out


def _stats(values: list[Any]) -> dict[str, Any]:
    numbers = _numeric(values)
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
        "zeros": sum(1 for item in numbers if item == 0),
    }


def preview(
    read: ReadResult,
    upload_sha256: str,
    payload: dict[str, Any],
    *,
    available_formats: list[str] | None = None,
) -> dict[str, Any]:
    fields = parse_spec(read, payload)
    compiled = compile_result(read, fields)
    variables = {variable.name: variable for variable in read.variables}
    field_previews = []
    for spec in fields:
        variable = variables[spec.name]
        column = read.columns[spec.name]
        affected = _affected_rows(read, spec)
        rules = []
        for override in spec.overrides:
            rows = affected.get(override.rule_id, [])
            before_analysis = [
                column["analysis"][row]
                for row in rows
                if column["analysis"][row] is not None
            ]
            after_values = []
            for row in rows:
                value = _analysis_for_override(
                    variable, override, column["raw"][row], column["ext_code"][row]
                )[0]
                after_values.append(value)
            variable_preview = {
                "rule_id": override.rule_id,
                "action": override.action,
                "value": json_scalar(override.value),
                "label": override.label,
                "affected_rows": rows[:PREVIEW_ROW_LIMIT],
                "affected_count": len(rows),
                "rows_truncated": len(rows) > PREVIEW_ROW_LIMIT,
                "before": _stats(before_analysis),
                "after": _stats(after_values),
                "states_before": sorted({column["state"][row] for row in rows}),
                "raw_values": sorted({str(column["raw"][row]) for row in rows}),
            }
            rules.append(variable_preview)
        field_previews.append(
            {
                "name": variable.name,
                "title": variable.label or variable.name,
                "classification": variable.classification,
                "storage_type": variable.storage_type,
                "source_format": variable.source_format,
                "time": variable.time.to_dict() if variable.time else None,
                "layers": spec.layers,
                "time_mode": spec.time_mode,
                "counts": read.counts(variable.name),
                "rules": [rule.to_dict() for rule in variable.rules],
                "overrides": rules,
                "warnings": _field_warnings(variable, spec),
            }
        )
    scope = {
        "fields": [spec.name for spec in fields],
        "rows": read.row_count,
        "output_columns": [column.name for column in compiled.columns],
        "layer_count": len(compiled.columns),
        "export_formats": available_formats or ["csv", "xlsx", "sav", "dta"],
    }
    return {
        "preview_token": spec_token(upload_sha256, payload),
        "canonical_spec": canonical_spec(payload),
        "fields": field_previews,
        "scope": scope,
        "notes": compiled.notes,
        "warnings": _global_warnings(read, fields),
        "confirmation_required": True,
        "original_immutable": True,
    }


def _field_warnings(variable: Any, spec: FieldSpec) -> list[str]:
    warnings: list[str] = []
    if spec.time_mode == "numeric" and variable.time is not None:
        warnings.append(
            f"{variable.name} 选择了保留原始数值：导出后不会保留日期标签，"
            "分析时必须自行按源格式与起点换算。"
        )
    if variable.classification == "unsupported":
        warnings.append(
            f"{variable.name} 的格式 {variable.source_format} 不受支持；"
            "raw 保留原值，analysis 为空，state=unsupported。"
        )
    for override in spec.overrides:
        if override.action == "valid" and variable.storage_type != "string" and override.rule_id.startswith("extended:"):
            warnings.append(
                f"{variable.name} 的扩展缺失码 {override.rule_id.split(':')[-1]} 没有原始数值，"
                "action=valid 不会产生有效值；请改用 set 并提供明确数值/日期。"
            )
        if override.action == "system":
            warnings.append(
                f"{variable.name}：转为系统缺失后，原缺失码仍保留在 raw/state 列中，但分析值变为空。"
            )
    return warnings


def _global_warnings(read: ReadResult, fields: list[FieldSpec]) -> list[str]:
    warnings = []
    if read.label_conflicts:
        warnings.append(
            "同一数值在不同字段上有不同标签/含义（例如 9、99）。本工具按字段保存标签，"
            "不使用全局字典替换。"
        )
    if any(variable.classification == "unsupported" for variable in read.variables):
        warnings.append("数据集中存在不支持的格式；这些字段不会被猜成普通数字。")
    return warnings
