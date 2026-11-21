"""Interpretation of SPSS and Stata date/time storage values.

Both systems store temporal values as plain numbers whose meaning depends
entirely on the variable's format.  This module keeps that interpretation
explicit: the source format, its epoch and its unit are recorded next to the
derived label/analysis value, and formats we cannot interpret are reported as
unsupported instead of being passed off as ordinary numbers.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

SPSS_EPOCH = datetime(1582, 10, 14, 0, 0, 0)
STATA_EPOCH = datetime(1960, 1, 1, 0, 0, 0)

SPSS_DATE_FORMATS = {
    "DATE",
    "ADATE",
    "EDATE",
    "JDATE",
    "SDATE",
    "DATETIME",
    "TIME",
    "DTIME",
    "MTIME",
    "WKDAY",
    "MONTH",
    "MOYR",
    "QYR",
    "WKYR",
}

SPSS_PARTIAL_DATE_FORMATS = {"WKDAY", "MONTH", "MOYR", "QYR", "WKYR"}

SPSS_NUMERIC_FORMATS = {
    "F",
    "COMMA",
    "DOT",
    "DOLLAR",
    "PCT",
    "E",
    "CC",
    "N",
    "Z",
    "P",
    "IB",
    "PIBHEX",
    "RB",
    "RZ",
    "PIB",
    "A",  # string, not temporal
}

STATA_SUPPORTED_TEMPORAL = {"td", "d", "tc", "tC", "tm", "tq", "th", "ty"}
STATA_UNSUPPORTED_TEMPORAL = {
    "tw": "Stata 的 %tw 周编号按年重置，换算依赖 Stata 的周定义；为避免猜错，本工具保留原值并标记为不支持",
    "tb": "Stata 的 %tb 为业务日（business date），跳过周末/节假日，无法从普通日历换算",
    "tg": "Stata 的 %tg 为通用时间格式，缺少明确的单位与起点",
}

_WEEKDAYS_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


@dataclass
class TimeSpec:
    """Everything needed to read a numeric storage value as a date/time."""

    supported: bool
    kind: str  # date | datetime | duration | month | quarter | half_year | year | unsupported
    source_format: str
    unit: Optional[str] = None
    epoch: Optional[str] = None
    reason: Optional[str] = None
    partial_display: bool = False
    leap_seconds: bool = False
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["notes"] = list(self.notes)
        return data


@dataclass
class Interpreted:
    label: Optional[str]
    display: Optional[str]
    analysis: Any
    analysis_state: str  # ok | missing | unsupported | invalid_value | out_of_range
    notes: tuple[str, ...] = ()


def _clean_format(fmt: Optional[str]) -> str:
    return (fmt or "").strip()


def parse_time_spec(fmt: Optional[str], storage_type: str) -> Optional[TimeSpec]:
    """Return a TimeSpec when the format carries temporal meaning.

    ``None`` means the format is an ordinary numeric/string display format.
    A TimeSpec with ``supported=False`` means the format looks temporal but we
    deliberately refuse to guess its meaning.
    """

    if storage_type == "string":
        return None
    raw = _clean_format(fmt)
    if not raw:
        return None

    if raw.startswith("%"):
        return _parse_stata_time_spec(raw)

    # SPSS format names are alphabetic followed by an optional width/precision.
    match = re.match(r"^([A-Za-z]+)(\d+)?(?:\.(\d+))?([A-Za-z_]*)$", raw)
    if match:
        base = match.group(1).upper()
        if base in SPSS_DATE_FORMATS:
            return _spss_time_spec(base, raw)
        if base in SPSS_NUMERIC_FORMATS:
            return None
        # e.g. an unfamiliar SPSS format.  If it smells temporal, refuse it.
        return TimeSpec(
            supported=False,
            kind="unsupported",
            source_format=raw,
            reason=(
                f"无法识别的 SPSS 数字格式 “{raw}”。无法确定它是否为日期/时间，"
                "因此不按普通数字推断其含义，原值保留。"
            ),
        )
    return TimeSpec(
        supported=False,
        kind="unsupported",
        source_format=raw,
        reason=f"无法解析的变量格式 “{raw}”，原值保留，不推断为日期或普通数字。",
    )


def _spss_time_spec(base: str, raw: str) -> TimeSpec:
    epoch = SPSS_EPOCH.isoformat()
    partial = base in SPSS_PARTIAL_DATE_FORMATS
    if base in {"DATE", "ADATE", "EDATE", "JDATE", "SDATE"}:
        return TimeSpec(
            supported=True,
            kind="date",
            source_format=raw,
            unit="seconds",
            epoch=epoch,
            partial_display=partial,
            notes=(
                "SPSS 日期以 1582-10-14 00:00:00（格里历）为零点、按秒存储。",
                "若底层值含一天内的时间而格式只显示日期，时间部分会单独标注。",
            ),
        )
    if base == "DATETIME":
        return TimeSpec(
            supported=True,
            kind="datetime",
            source_format=raw,
            unit="seconds",
            epoch=epoch,
            notes=("SPSS 日期时间以 1582-10-14 00:00:00 为零点、按秒存储。",),
        )
    if base in {"TIME", "DTIME", "MTIME"}:
        return TimeSpec(
            supported=True,
            kind="duration",
            source_format=raw,
            unit="seconds",
            epoch=None,
            notes=(
                f"SPSS 的 {base} 是时长/时刻偏移（秒），没有日历起点；不要当作日期使用。",
            ),
        )
    if base in {"WKDAY", "MONTH", "MOYR", "QYR", "WKYR"}:
        return TimeSpec(
            supported=True,
            kind="date",
            source_format=raw,
            unit="seconds",
            epoch=epoch,
            partial_display=True,
            notes=(
                "SPSS 日期以 1582-10-14 00:00:00 为零点、按秒存储。",
                f"源格式 {base} 只显示部分日期字段；底层仍是完整日期，分析值保留完整日期。",
            ),
        )
    return TimeSpec(
        supported=False,
        kind="unsupported",
        source_format=raw,
        reason=f"未实现的 SPSS 时间格式 {raw}",
    )


def _parse_stata_time_spec(raw: str) -> Optional[TimeSpec]:
    body = raw[1:]
    # Strip optional '-', width and precision: %-9.0f, %10.0g, %td...
    m = re.match(r"^-?\d*(?:\.\d+)?(.*)$", body)
    body = m.group(1) if m else body

    token = None
    for candidate in ("tC", "tc", "td", "tm", "tq", "th", "tw", "ty", "tb", "tg"):
        if body.startswith(candidate):
            token = candidate
            break
    if token is None and body.startswith("d"):
        # Stata's old %d date format.
        token = "d"

    if token is None:
        return None

    if token in STATA_UNSUPPORTED_TEMPORAL:
        return TimeSpec(
            supported=False,
            kind="unsupported",
            source_format=raw,
            reason=STATA_UNSUPPORTED_TEMPORAL[token],
        )

    if token in {"td", "d"}:
        return TimeSpec(
            supported=True,
            kind="date",
            source_format=raw,
            unit="days",
            epoch=STATA_EPOCH.isoformat(),
            notes=("Stata %td 以 1960-01-01 为零点、按天存储。",),
        )
    if token == "tc":
        return TimeSpec(
            supported=True,
            kind="datetime",
            source_format=raw,
            unit="milliseconds",
            epoch=STATA_EPOCH.isoformat(),
            notes=("Stata %tc 以 1960-01-01 00:00:00 为零点、按毫秒存储。",),
        )
    if token == "tC":
        return TimeSpec(
            supported=True,
            kind="datetime",
            source_format=raw,
            unit="milliseconds",
            epoch=STATA_EPOCH.isoformat(),
            leap_seconds=True,
            notes=(
                "Stata %tC 以 1960-01-01 00:00:00 为零点、按毫秒存储，并使用连续时间（闰秒）标度。",
                "本工具没有内置闰秒表，仅按毫秒换算；闰秒差异未应用，已在分析值旁标注。",
            ),
        )
    if token == "tm":
        return TimeSpec(
            supported=True,
            kind="month",
            source_format=raw,
            unit="months",
            epoch="1960-01",
            notes=("Stata %tm 以 1960m1 为 0、按月存储。",),
        )
    if token == "tq":
        return TimeSpec(
            supported=True,
            kind="quarter",
            source_format=raw,
            unit="quarters",
            epoch="1960q1",
            notes=("Stata %tq 以 1960q1 为 0、按季度存储。",),
        )
    if token == "th":
        return TimeSpec(
            supported=True,
            kind="half_year",
            source_format=raw,
            unit="half-years",
            epoch="1960h1",
            notes=("Stata %th 以 1960h1 为 0、按半年存储。",),
        )
    if token == "ty":
        return TimeSpec(
            supported=True,
            kind="year",
            source_format=raw,
            unit="years",
            epoch="year 0",
            notes=("Stata %ty 的值就是日历年本身。",),
        )
    return TimeSpec(
        supported=False,
        kind="unsupported",
        source_format=raw,
        reason=f"未实现的 Stata 时间格式 {raw}",
    )


def _is_integral(value: float, tolerance: float = 1e-9) -> bool:
    return abs(value - round(value)) <= tolerance


def _fmt_fraction(seconds: float) -> str:
    micros = int(round((seconds - math.floor(seconds)) * 1_000_000))
    if micros == 0:
        return ""
    return "." + f"{micros:06d}".rstrip("0")


def _iso(dt: datetime, include_time: bool) -> str:
    if not include_time:
        return dt.date().isoformat()
    text = dt.strftime("%Y-%m-%dT%H:%M:%S")
    frac = _fmt_fraction(dt.microsecond / 1_000_000)
    return text + frac


def _spss_label(base: str, dt: datetime, has_time: bool) -> str:
    if base in {"DATE", "ADATE", "EDATE", "JDATE", "SDATE"}:
        return dt.date().isoformat()
    if base == "DATETIME":
        return dt.strftime("%Y-%m-%d %H:%M:%S") + _fmt_fraction(
            dt.microsecond / 1_000_000
        )
    if base == "TIME":
        seconds = (
            dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1_000_000
        )
        return _duration_label(seconds, with_days=False)
    if base == "DTIME":
        seconds = (
            dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1_000_000
        )
        return _duration_label(seconds, with_days=True)
    if base == "MTIME":
        return dt.strftime("%M:%S") + _fmt_fraction(dt.microsecond / 1_000_000)
    if base == "WKDAY":
        return _WEEKDAYS_ZH[dt.weekday()]
    if base == "MONTH":
        return f"{dt.month}月"
    if base == "MOYR":
        return dt.strftime("%Y-%m")
    if base == "QYR":
        return f"{dt.year}Q{(dt.month - 1) // 3 + 1}"
    if base == "WKYR":
        iso_year, iso_week, _ = dt.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    return dt.isoformat()


def _duration_label(seconds: float, with_days: bool) -> str:
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    sec_text = f"{int(secs):02d}" + _fmt_fraction(secs)
    if with_days:
        return f"{sign}{int(days)} 天 {int(hours):02d}:{int(minutes):02d}:{sec_text}"
    total_hours = int(days * 24 + hours)
    return f"{sign}{total_hours:02d}:{int(minutes):02d}:{sec_text}"


def interpret_value(raw: Any, spec: TimeSpec) -> Interpreted:
    """Interpret a numeric storage value according to its TimeSpec."""

    if not spec.supported:
        return Interpreted(
            label=None,
            display=None,
            analysis=None,
            analysis_state="unsupported",
            notes=(spec.reason or "不支持的格式",),
        )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return Interpreted(None, None, None, "invalid_value", ("值不是数字",))
    if not math.isfinite(value):
        return Interpreted(None, None, None, "invalid_value", ("值不是有限数字",))

    try:
        if spec.kind == "duration":
            seconds = value
            fmt_upper = spec.source_format.upper().rstrip("0123456789.")
            if fmt_upper.startswith("MTIME"):
                label = _duration_label(seconds, with_days=False)
                # MTIME displays mm:ss; use a compact mm:ss form.
                minutes, secs = divmod(abs(seconds), 60)
                label = ("-" if seconds < 0 else "") + f"{int(minutes):02d}:{secs:05.2f}"
            elif fmt_upper.startswith("DTIME"):
                label = _duration_label(seconds, with_days=True)
            else:
                label = _duration_label(seconds, with_days=False)
            return Interpreted(
                label=label,
                display=label,
                analysis=seconds,
                analysis_state="ok",
                notes=("时长按秒分析；它不是日历日期。",),
            )

        if spec.kind == "year":
            if not _is_integral(value):
                return Interpreted(
                    None,
                    None,
                    None,
                    "invalid_value",
                    ("%ty 年份不是整数，无法可靠解释",),
                )
            year = int(round(value))
            return Interpreted(str(year), str(year), year, "ok")

        if spec.kind in {"month", "quarter", "half_year"}:
            if not _is_integral(value):
                return Interpreted(
                    None,
                    None,
                    None,
                    "invalid_value",
                    ("周期值不是整数，无法可靠解释",),
                )
            n = int(round(value))
            if spec.kind == "month":
                year = 1960 + n // 12
                month = n % 12 + 1
                start = datetime(year, month, 1)
                label = f"{year}m{month}"
                end_month = month + 1
                end_year = year
                if end_month == 13:
                    end_month, end_year = 1, year + 1
                end = datetime(end_year, end_month, 1) - timedelta(days=1)
            elif spec.kind == "quarter":
                year = 1960 + n // 4
                quarter = n % 4 + 1
                start = datetime(year, (quarter - 1) * 3 + 1, 1)
                label = f"{year}q{quarter}"
                end_month = quarter * 3
                end = datetime(year, end_month, 1) + timedelta(days=31)
                end = (end.replace(day=1) - timedelta(days=1))
            else:
                year = 1960 + n // 2
                half = n % 2 + 1
                start = datetime(year, 1 if half == 1 else 7, 1)
                label = f"{year}h{half}"
                if half == 1:
                    end = datetime(year, 6, 30)
                else:
                    end = datetime(year, 12, 31)
            return Interpreted(
                label=label,
                display=label,
                analysis=start.date().isoformat(),
                analysis_state="ok",
                notes=(
                    f"周期值 {n} 解释为 {label}，分析值取该周期第一天 {start.date().isoformat()}；"
                    f"周期范围 {start.date().isoformat()} 至 {end.date().isoformat()}。",
                ),
            )

        if spec.kind == "date" and spec.unit == "days":
            if not _is_integral(value):
                # Fractional days carry a time of day; keep the full instant.
                dt = STATA_EPOCH + timedelta(days=value)
                note = "存储值含一天内的小数部分，已保留为日期时间。"
                return Interpreted(
                    label=_iso(dt, True),
                    display=_iso(dt, True),
                    analysis=_iso(dt, True),
                    analysis_state="ok",
                    notes=(note,),
                )
            dt = STATA_EPOCH + timedelta(days=value)
            return Interpreted(
                label=dt.date().isoformat(),
                display=dt.date().isoformat(),
                analysis=dt.date().isoformat(),
                analysis_state="ok",
            )

        if spec.kind in {"date", "datetime"} and spec.unit == "seconds":
            if abs(value) > 1e15:
                return Interpreted(
                    None, None, None, "out_of_range", ("秒数超出可解释范围",)
                )
            dt = SPSS_EPOCH + timedelta(seconds=value)
            base = re.match(r"^([A-Za-z]+)", spec.source_format)
            base_name = (base.group(1) if base else "").upper()
            has_time = (
                dt.hour != 0
                or dt.minute != 0
                or dt.second != 0
                or dt.microsecond != 0
            )
            label = _spss_label(base_name, dt, has_time)
            include_time = (
                spec.kind == "datetime"
                or base_name == "DATETIME"
                or has_time
            )
            analysis = _iso(dt, include_time)
            notes: tuple[str, ...] = ()
            if has_time and base_name not in {"DATETIME", "TIME", "DTIME", "MTIME"}:
                notes = (
                    "底层值包含一天内的时间，但源格式只显示日期；分析值保留完整时间。",
                )
            return Interpreted(
                label=label,
                display=label,
                analysis=analysis,
                analysis_state="ok",
                notes=notes,
            )

        if spec.kind == "datetime" and spec.unit == "milliseconds":
            seconds = value / 1000.0
            if abs(seconds) > 1e15:
                return Interpreted(
                    None, None, None, "out_of_range", ("毫秒数超出可解释范围",)
                )
            dt = STATA_EPOCH + timedelta(seconds=seconds)
            label = dt.strftime("%Y-%m-%d %H:%M:%S") + _fmt_fraction(
                dt.microsecond / 1_000_000
            )
            notes = ()
            if spec.leap_seconds:
                notes = ("%tC 的闰秒标度未转换（缺少闰秒表），按连续毫秒解释。",)
            return Interpreted(
                label=label,
                display=label,
                analysis=_iso(dt, True),
                analysis_state="ok",
                notes=notes,
            )

        return Interpreted(
            None, None, None, "unsupported", (spec.reason or "不支持的时间类型",)
        )
    except (OverflowError, ValueError, OSError) as exc:
        return Interpreted(
            None,
            None,
            None,
            "out_of_range",
            (f"数值超出可解释范围：{exc}",),
        )


def analysis_to_raw(analysis: Any, spec: TimeSpec) -> tuple[float, list[str]]:
    """Convert an ISO analysis value back to the source storage unit."""

    notes: list[str] = []
    if isinstance(analysis, (int, float)) and spec.kind in {"duration", "year"}:
        return float(analysis), notes
    text = str(analysis).strip()
    if not text:
        raise ValueError("分析值不能为空")
    dt = _parse_iso(text)
    if spec.kind == "duration":
        midnight = datetime(1900, 1, 1)
        return (dt - midnight).total_seconds(), notes
    if spec.kind == "date" and spec.unit == "days":
        return (dt - STATA_EPOCH).total_seconds() / 86400.0, notes
    if spec.kind == "date" and spec.unit == "seconds":
        return (dt - SPSS_EPOCH).total_seconds(), notes
    if spec.kind == "datetime" and spec.unit == "milliseconds":
        return (dt - STATA_EPOCH).total_seconds() * 1000.0, notes
    if spec.kind == "month":
        months = (dt.year - 1960) * 12 + (dt.month - 1)
        return float(months), notes
    if spec.kind == "quarter":
        quarters = (dt.year - 1960) * 4 + (dt.month - 1) // 3
        return float(quarters), notes
    if spec.kind == "half_year":
        halves = (dt.year - 1960) * 2 + (1 if dt.month >= 7 else 0)
        return float(halves), notes
    if spec.kind == "year":
        return float(dt.year), notes
    raise ValueError(f"不支持的目标时间类型 {spec.kind}")


def _parse_iso(text: str) -> datetime:
    value = text.strip()
    if value.endswith("Z"):
        value = value[:-1]
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        try:
            d = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"无法解析日期/时间 “{text}”，请使用 ISO 格式") from exc
        dt = datetime(d.year, d.month, d.day)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
