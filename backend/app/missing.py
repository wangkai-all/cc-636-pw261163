"""Missing-value semantics.

Three families are kept apart on purpose:

* ``system``   - blank/NaN (SPSS and Stata system missing).
* ``user``     - SPSS user-defined missing values (discrete codes or ranges),
                 which are ordinary stored values carrying a missing meaning.
* ``extended`` - Stata extended missing codes ``.a`` .. ``.z``.

A stored code can be missing in one variable and valid in another, so rules
and value labels are always attached to a single variable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .values import canonical_number, json_scalar, number_key

EXT_LETTERS = "abcdefghijklmnopqrstuvwxyz"


@dataclass
class MissingRule:
    id: str
    kind: str  # user | extended | system
    code: Optional[str] = None
    low: Any = None
    high: Any = None
    label: Optional[str] = None
    source: str = ""
    description: str = ""
    value_kind: str = "numeric"  # numeric | string

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "code": self.code,
            "low": json_scalar(self.low),
            "high": json_scalar(self.high),
            "label": self.label,
            "source": self.source,
            "description": self.description,
            "value_kind": self.value_kind,
        }

    @property
    def is_range(self) -> bool:
        return (
            self.value_kind == "numeric"
            and self.low is not None
            and self.high is not None
            and float(self.low) != float(self.high)
        )

    def matches(self, value: Any, ext_code: Optional[str] = None) -> bool:
        if self.kind == "system":
            return value is None
        if self.kind == "extended":
            return ext_code is not None and ext_code == self.code
        if self.value_kind == "string":
            return isinstance(value, str) and self.code is not None and value == self.code
        if isinstance(value, bool) or value is None:
            return False
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        if self.is_range:
            return float(self.low) <= number <= float(self.high)
        if self.code is None:
            return False
        try:
            return number == float(self.code)
        except (TypeError, ValueError):
            return False


def system_rule() -> MissingRule:
    return MissingRule(
        id="system",
        kind="system",
        source="system",
        description="系统缺失（空白数值 / 空字符串）",
    )


def _lookup_label(value: Any, value_labels: dict[Any, str]) -> Optional[str]:
    if not value_labels:
        return None
    key = number_key(value)
    for label_value, text in value_labels.items():
        if number_key(label_value) == key:
            return text
    return None


def build_rules(
    *,
    variable: str,
    file_type: str,
    storage_type: str,
    value_labels: dict[Any, str],
    missing_ranges: list[dict[str, Any]] | None,
    missing_user_values: list[str] | None,
) -> list[MissingRule]:
    """Build per-variable missing rules from raw reader metadata."""

    rules: list[MissingRule] = []
    labels = value_labels or {}

    if file_type == "sav":
        for item in missing_ranges or []:
            try:
                lo = item.get("lo")
                hi = item.get("hi", lo)
            except AttributeError:
                lo = hi = item
            if isinstance(lo, str) or isinstance(hi, str):
                text = lo if isinstance(lo, str) else hi
                rules.append(
                    MissingRule(
                        id=f"user:{variable}:str:{text}",
                        kind="user",
                        code=text,
                        low=text,
                        high=hi if isinstance(hi, str) else text,
                        label=text,
                        source="SPSS 用户定义缺失",
                        description=f"字符串取值 “{text}” 被声明为用户缺失",
                        value_kind="string",
                    )
                )
                continue
            if lo is None:
                continue
            hi_value = lo if hi is None else hi
            if float(lo) == float(hi_value):
                rules.append(
                    MissingRule(
                        id=f"user:{variable}:{canonical_number(lo)}",
                        kind="user",
                        code=canonical_number(lo),
                        low=lo,
                        high=hi_value,
                        label=_lookup_label(lo, labels),
                        source="SPSS 用户定义缺失（离散值）",
                        description=f"存储值 {canonical_number(lo)} 被声明为用户缺失",
                    )
                )
            else:
                rules.append(
                    MissingRule(
                        id=f"user:{variable}:range:{canonical_number(lo)}:{canonical_number(hi_value)}",
                        kind="user",
                        code=None,
                        low=lo,
                        high=hi_value,
                        label=None,
                        source="SPSS 用户定义缺失（范围）",
                        description=(
                            f"存储值落在 {canonical_number(lo)} 至 "
                            f"{canonical_number(hi_value)} 之间时视为用户缺失"
                        ),
                    )
                )
    elif file_type == "dta":
        for letter in missing_user_values or []:
            clean = letter[1:] if letter.startswith(".") else letter
            code = "." + clean.lower()
            if code == ".":
                continue
            rules.append(
                MissingRule(
                    id=f"extended:{variable}:{code}",
                    kind="extended",
                    code=code,
                    label=None,
                    source="Stata 扩展缺失码",
                    description=f"Stata 扩展缺失码 {code}",
                )
            )
    return rules


def rule_for_code(rules: list[MissingRule], ext_code: Optional[str]) -> Optional[MissingRule]:
    if not ext_code:
        return None
    for rule in rules:
        if rule.kind == "extended" and rule.code == ext_code:
            return rule
    return None
