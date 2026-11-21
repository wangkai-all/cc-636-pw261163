"""Low-level DTA helpers pyreadstat/pandas do not expose.

Only two things are needed here:

* locate the data section of a dta 117+ file and patch a numeric cell with a
  Stata extended missing code (``.a`` .. ``.z``), which neither pyreadstat nor
  pandas can write;
* read those codes back (pyreadstat already returns ``.a`` strings when
  ``user_missing=True``, so reading is delegated).

Supported storage codes are the ones pandas/pyreadstat emit:
int8 (65530), int16 (65529), int32 (65528), float (65527), double (65526).
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, Optional

from .values import ext_index

TYPE_WIDTH = {
    65526: 8,  # double
    65527: 4,  # float
    65528: 4,  # int32
    65529: 2,  # int16
    65530: 1,  # int8
}
TYPE_NAME = {
    65526: "double",
    65527: "float",
    65528: "int32",
    65529: "int16",
    65530: "int8",
}

INT_MISSING_BASE = {65530: 101, 65529: 32741, 65528: 2147483621}


class DtaLayoutError(ValueError):
    pass


def _section(buffer: bytes, name: str) -> Optional[bytes]:
    open_tag = f"<{name}>".encode()
    close_tag = f"</{name}>".encode()
    start = buffer.find(open_tag)
    end = buffer.find(close_tag)
    if start < 0 or end < 0 or end < start:
        return None
    return buffer[start + len(open_tag) : end]


def parse_layout(path: str | Path) -> dict[str, Any]:
    data = Path(path).read_bytes()
    if not data.startswith(b"<stata_dta>"):
        raise DtaLayoutError("缺少 <stata_dta> 文件头")
    release = _section(data, "release")
    if release is None:
        raise DtaLayoutError("不是 Stata 117+ 的 <stata_dta> 文件")
    release_text = release.decode("ascii", "replace").strip("\x00")
    k_bytes = _section(data, "K")
    n_bytes = _section(data, "N")
    types_bytes = _section(data, "variable_types")
    if k_bytes is None or n_bytes is None or types_bytes is None:
        raise DtaLayoutError("缺少 K/N/variable_types 段")
    k = struct.unpack("<H", k_bytes)[0] if len(k_bytes) == 2 else struct.unpack("<I", k_bytes)[0]
    n = struct.unpack("<I", n_bytes[:4])[0]
    types = struct.unpack("<" + "H" * k, types_bytes[: 2 * k])
    widths = []
    for code in types:
        if code <= 2045:  # str# fixed width
            widths.append(code)
        elif code == 32768:  # strL reference
            widths.append(8)
        elif code in TYPE_WIDTH:
            widths.append(TYPE_WIDTH[code])
        else:
            raise DtaLayoutError(f"未知的存储类型码 {code}")
    data_start = data.find(b"<data>")
    if data_start < 0:
        raise DtaLayoutError("缺少 <data> 段")
    return {
        "release": release_text,
        "k": k,
        "n": n,
        "types": list(types),
        "widths": widths,
        "row_width": sum(widths),
        "data_start": data_start + len(b"<data>"),
        "data_length": len(data),
    }


def ext_missing_bytes(type_code: int, code: str) -> bytes:
    index = ext_index(code)
    if not 1 <= index <= 26:
        raise ValueError(f"扩展缺失码超出 .a-.z 范围：{code}")
    if type_code == 65530:
        return struct.pack("<b", INT_MISSING_BASE[type_code] + index)
    if type_code == 65529:
        return struct.pack("<h", INT_MISSING_BASE[type_code] + index)
    if type_code == 65528:
        return struct.pack("<i", INT_MISSING_BASE[type_code] + index)
    if type_code == 65527:
        # Stata float32 missing pattern: 0x7f000000 + index * 0x00000800.
        raw = 0x7F000000 + index * 0x00000800
        return struct.pack("<I", raw)
    if type_code == 65526:
        raw = 0x7FE0000000000000 + index * (1 << 40)
        return struct.pack("<Q", raw)
    raise DtaLayoutError(f"存储类型 {type_code} 不支持扩展缺失码")


def patch_extended_missing(
    path: str | Path,
    column_index: int,
    row_indices: list[int],
    code: str,
) -> None:
    """Patch selected cells of one numeric column to ``code`` (e.g. ``.a``)."""

    layout = parse_layout(path)
    type_code = layout["types"][column_index]
    if type_code not in TYPE_WIDTH:
        raise DtaLayoutError("只有数值列可以写扩展缺失码")
    payload = ext_missing_bytes(type_code, code)
    column_offset = sum(layout["widths"][:column_index])
    raw = bytearray(Path(path).read_bytes())
    for row in row_indices:
        offset = layout["data_start"] + row * layout["row_width"] + column_offset
        raw[offset : offset + len(payload)] = payload
    Path(path).write_bytes(bytes(raw))
