from __future__ import annotations

import shutil
import struct
from pathlib import Path

import pytest

from app.dta_io import ext_missing_bytes, parse_layout, patch_extended_missing

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def dta_copy(tmp_path) -> Path:
    target = tmp_path / "demo.dta"
    shutil.copy(ROOT / "samples" / "demo_intake.dta", target)
    return target


def test_layout_locates_data(dta_copy):
    layout = parse_layout(dta_copy)
    assert layout["release"] == "119"
    assert layout["k"] == 12 and layout["n"] == 12
    assert layout["row_width"] > 0
    assert layout["data_start"] > 0


def test_ext_missing_byte_patterns():
    # double: base 0x7fe0000000000000 + index << 40
    assert struct.unpack("<Q", ext_missing_bytes(65526, ".a"))[0] == 0x7FE0000000000000 + (1 << 40)
    # float: 0x7f000000 + index * 0x800
    assert struct.unpack("<I", ext_missing_bytes(65527, ".b"))[0] == 0x7F000000 + 2 * 0x800
    # integers use 101+n / 32741+n / 2147483621+n
    assert struct.unpack("<b", ext_missing_bytes(65530, ".c"))[0] == 101 + 3
    assert struct.unpack("<h", ext_missing_bytes(65529, ".a"))[0] == 32741 + 1
    assert struct.unpack("<i", ext_missing_bytes(65528, ".z"))[0] == 2147483621 + 26


def test_ext_missing_rejects_strings_and_out_of_range():
    # int8 .z = 127 is the last storable code; anything beyond must fail.
    assert struct.unpack("<b", ext_missing_bytes(65530, ".z"))[0] == 127
    with pytest.raises(Exception):
        ext_missing_bytes(20, ".a")
    with pytest.raises(Exception):
        ext_missing_bytes(65526, ".1")


def test_patch_roundtrip_is_read_back_as_extended_code(dta_copy):
    import pyreadstat

    layout = parse_layout(dta_copy)
    names = list(
        pyreadstat.read_dta(str(dta_copy), disable_datetime_conversion=True)[0].columns
    )
    index = names.index("age")
    patch_extended_missing(dta_copy, index, [0], ".d")
    frame, _meta = pyreadstat.read_dta(
        str(dta_copy), user_missing=True, disable_datetime_conversion=True
    )
    assert frame["age"].iloc[0] == "d" or str(frame["age"].iloc[0]).lstrip(".") == "d"
    # Untouched rows keep their values.
    assert frame["age"].iloc[1] == 34
    layout_after = parse_layout(dta_copy)
    assert layout_after["n"] == layout["n"]
