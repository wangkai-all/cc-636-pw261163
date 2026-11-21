"""Build the two demo files used by the intake desk.

The files deliberately exercise the hard cases:

* a labelled valid zero (``0`` with a value label, not missing);
* system missing, SPSS user-missing (discrete and range), SPSS string
  user-missing, and Stata extended missing ``.a``/``.b``/``.c``;
* the same stored code meaning different things in different variables
  (``9`` is a valid education level but a refusal code for ``group``;
  ``99`` is a valid age but a refusal code for ``satisfaction``);
* dates and datetimes stored on the SPSS 1582 epoch and the Stata 1960
  epoch, plus Stata ``%tm`` months and an unsupported ``%tw`` week column;
* long Chinese strings where stored byte width, display width and Stata
  strL storage differ.

Run:  python scripts/build_samples.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.dta_io import patch_extended_missing  # noqa: E402

SAMPLES = ROOT / "samples"

LONG_CN = (
    "这是一段很长的中文备注，用来验证存储宽度按字节计算、显示宽度按字符计算，"
    "两者并不相同；同时验证中文文本在 SPSS 固定宽度与 Stata strL 中的保存方式。"
)
VERY_LONG_CN = (
    "超长中文备注：" + "用于验证 Stata 的 strL 长字符串不会截断，也不会把显示宽度当成存储宽度。" * 60
)

ROWS = [
    # pid, group, satisfaction, age, edu, visit, started, note, remark, call_duration
    (1001, 0, 0.0, 23, 9, "2020-01-01", "2020-01-01 08:30:00", LONG_CN, "正常", 75.5),
    (1002, 1, 5.0, 34, 12, "2020-02-29", "2020-02-29 09:15:30", "短备注", "拒答", 120.0),
    (1003, 2, 3.0, 41, 15, "2020-03-15", "2020-03-15 12:00:00", "正常文本", "", 3600.0),
    (1004, 0, 0.0, -5, 9, "2021-07-01", "2021-07-01 23:59:59", "第三条", "正常", 0.0),
    (1005, 1, 4.0, 58, 16, "2022-12-31", "2022-12-31 00:00:00", "", "正常", 5.25),
    (1006, 2, 2.0, 99, 12, "2023-06-01", "2023-06-01 16:45:10", VERY_LONG_CN, "拒答", 90.0),
    (1007, 0, 5.0, 29, 9, "2023-07-04", "2023-07-04 07:05:00", "带，标点。", "正常", 12.0),
    (1008, 1, 0.0, 36, 18, "2023-08-15", "2023-08-15 18:30:00", "备注一", "", 600.0),
    (1009, 2, 1.0, 42, 12, "2023-09-30", "2023-09-30 10:10:10", "备注二", "拒答", 30.0),
    (1010, 0, 3.0, -3, 15, "2023-10-01", "2023-10-01 11:11:11", "备注三", "正常", 0.5),
    (1011, 1, 4.0, 51, 9, "2023-11-11", "2023-11-11 12:12:12", "备注四", "正常", 45.0),
    (1012, 2, 2.0, 44, 12, "2023-12-31", "2023-12-31 13:13:13", "备注五", "拒答", 8.0),
]

GROUP_LABELS = {0: "对照组（有效零）", 1: "干预组", 2: "观察组", 9: "拒答"}
SATISFACTION_LABELS = {
    0: "零分（有效零值）",
    1: "非常不满意",
    2: "不满意",
    3: "一般",
    4: "满意",
    5: "非常满意",
    99: "拒答",
}
AGE_LABELS = {99: "99 岁（有效值）", -5: "不适用"}
EDU_LABELS = {9: "九年级", 12: "高中毕业", 15: "大专", 16: "本科", 18: "硕士"}


def build_frame() -> pd.DataFrame:
    records = []
    for pid, group, satisfaction, age, edu, visit, started, note, remark, call in ROWS:
        records.append(
            {
                "pid": pid,
                "group": group,
                "satisfaction": satisfaction,
                "age": age,
                "edu_years": edu,
                "visit_date": visit,
                "started_at": started,
                "note": note,
                "remark": remark,
                "call_duration": call,
            }
        )
    frame = pd.DataFrame(records)
    frame["pid"] = frame["pid"].astype("float64")
    frame["group"] = frame["group"].astype("float64")
    frame["satisfaction"] = frame["satisfaction"].astype("float64")
    frame["age"] = frame["age"].astype("float64")
    frame["edu_years"] = frame["edu_years"].astype("float64")
    frame["call_duration"] = frame["call_duration"].astype("float64")
    return frame


LABELS = {
    "pid": "受访者编号",
    "group": "分组",
    "satisfaction": "满意度得分",
    "age": "年龄",
    "edu_years": "受教育年限",
    "visit_date": "访视日期",
    "started_at": "访谈开始时间",
    "note": "开放题备注",
    "remark": "访员备注",
    "call_duration": "通话时长",
}


def build_sav(frame: pd.DataFrame) -> None:
    data = frame.copy()
    # SPSS user-missing: discrete codes and a range, plus a string code.
    data.loc[11, "group"] = 9
    data.loc[1, "satisfaction"] = 99
    data.loc[3, "age"] = -5
    data.loc[9, "age"] = -3
    data.loc[5, "visit_date"] = None
    data.loc[8, "started_at"] = None
    data = data.astype(
        {
            "pid": "int32",
            "group": "int8",
            "satisfaction": "float64",
            "age": "int16",
            "edu_years": "int8",
            "visit_date": "datetime64[us]",
            "started_at": "datetime64[us]",
            "note": "object",
            "remark": "object",
            "call_duration": "float64",
        }
    )
    path = SAMPLES / "demo_intake.sav"
    pyreadstat.write_sav(
        data,
        str(path),
        file_label="收件台演示数据（SPSS）",
        column_labels=LABELS,
        variable_value_labels={
            "group": GROUP_LABELS,
            "satisfaction": SATISFACTION_LABELS,
            "age": AGE_LABELS,
            "edu_years": EDU_LABELS,
        },
        missing_ranges={
            "group": [9],
            "satisfaction": [99],
            "age": [{"lo": -9, "hi": -1}],
            "remark": ["拒答"],
        },
        variable_display_width={"note": 40, "remark": 8},
        variable_format={
            "visit_date": "DATE11",
            "started_at": "DATETIME20",
            "call_duration": "MTIME10",
            "pid": "F8.0",
            "group": "F8.0",
            "age": "F8.0",
            "edu_years": "F8.0",
        },
        variable_measure={
            "group": "nominal",
            "satisfaction": "scale",
            "age": "scale",
            "edu_years": "ordinal",
            "visit_date": "scale",
            "note": "nominal",
        },
    )
    print(f"wrote {path} ({path.stat().st_size} bytes)")


def build_dta(frame: pd.DataFrame) -> None:
    data = frame.copy()
    data["pid"] = data["pid"].astype("int32")
    data["group"] = data["group"].astype("int8")
    data["edu_years"] = data["edu_years"].astype("int8")
    data["age"] = data["age"].astype("int16")

    visit = pd.to_datetime(data["visit_date"])
    started = pd.to_datetime(data["started_at"])
    epoch = pd.Timestamp("1960-01-01")
    data["visit_date"] = (visit - epoch).dt.total_seconds() / 86400.0
    data["started_at"] = (started - epoch).dt.total_seconds() * 1000.0

    # Stata period columns (%tm months since 1960m1, %tw ISO week).
    data["period"] = ((visit.dt.year - 1960) * 12 + visit.dt.month - 1).astype("float64")
    data["week"] = visit.dt.isocalendar().week.astype("float64")

    # Extended missing codes need real NaN in the frame first; the integer
    # columns keep their int8/int16 storage because the placeholder values are
    # patched to .a/.c in the raw bytes afterwards.
    data.loc[11, "group"] = 0
    data.loc[1, "satisfaction"] = 0.0
    data.loc[3, "age"] = 0
    data.loc[9, "age"] = 0
    data.loc[5, "visit_date"] = np.nan
    data.loc[8, "started_at"] = np.nan
    data.loc[5, "period"] = np.nan
    data.loc[5, "week"] = np.nan

    path = SAMPLES / "demo_intake.dta"
    pyreadstat.write_dta(
        data,
        str(path),
        version=15,
        file_label="收件台演示数据（Stata）",
        column_labels={**LABELS, "period": "访视月份", "week": "ISO 周编号"},
        variable_value_labels={
            "group": GROUP_LABELS,
            "satisfaction": SATISFACTION_LABELS,
            "age": AGE_LABELS,
            "edu_years": EDU_LABELS,
        },
        variable_format={
            "visit_date": "%td",
            "started_at": "%tc",
            "period": "%tm",
            "week": "%tw",
            "pid": "%8.0g",
            "group": "%8.0g",
            "age": "%8.0g",
            "edu_years": "%8.0g",
        },
    )
    # Column order used by the written file:
    names = [
        "pid",
        "group",
        "satisfaction",
        "age",
        "edu_years",
        "visit_date",
        "started_at",
        "note",
        "remark",
        "call_duration",
        "period",
        "week",
    ]
    patch_extended_missing(path, names.index("group"), [11], ".a")
    patch_extended_missing(path, names.index("satisfaction"), [1], ".b")
    patch_extended_missing(path, names.index("age"), [3, 9], ".c")
    print(f"wrote {path} ({path.stat().st_size} bytes)")


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    frame = build_frame()
    build_sav(frame)
    build_dta(frame)


if __name__ == "__main__":
    main()
