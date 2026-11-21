"""Supported export formats and their limitations."""

from __future__ import annotations

EXPORT_FORMATS = ["csv", "xlsx", "sav", "dta"]

FORMAT_TITLES = {
    "csv": "CSV（UTF-8，附 schema.json）",
    "xlsx": "Excel 工作簿（data + dictionary）",
    "sav": "SPSS SAV",
    "dta": "Stata DTA",
}

FORMAT_NOTES = {
    "csv": "纯文本，不含标签；schema.json 随结果保存标签与缺失规则。",
    "xlsx": "dictionary 工作表承载标签/缺失规则；缺失单元格为空。",
    "sav": "保留变量标签、值标签与 SPSS 用户定义缺失（含范围与字符串缺失）。",
    "dta": "保留变量标签与值标签；原始值列可写回 Stata 扩展缺失码 .a-.z。",
}

FORMAT_LIMITS = {
    "sav": [
        "日期列以原始存储数值导出并恢复源格式，导入 SPSS 后按格式显示。",
        "显示宽度按列内最长值重算，原始文件中的显示宽度记录在清单里。",
    ],
    "dta": [
        "Stata 没有 SPSS 的变量显示宽度；字符串按实际内容保存。",
        "SPSS 用户定义缺失（离散码/范围）在 DTA 中没有等价物，只有扩展缺失码可写回。",
    ],
    "csv": ["所有单元格以文本写出；日期保持 ISO 文本，缺失保持空字符串。"],
    "xlsx": ["所有单元格以文本/数字写出；dictionary 工作表是恢复含义的唯一来源。"],
}
