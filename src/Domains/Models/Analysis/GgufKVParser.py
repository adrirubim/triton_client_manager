from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Final


class GgufKVParseError(ValueError):
    pass


_GGUF_MAGIC: Final[bytes] = b"GGUF"

# Hard safety caps (defense-in-depth against malformed files).
_MAX_KV_ENTRIES: Final[int] = 50_000
_MAX_STRING_BYTES: Final[int] = 1_000_000  # 1 MB
_MAX_ARRAY_ELEMENTS: Final[int] = 2_000_000


class _ValueType:
    UINT8 = 0
    INT8 = 1
    UINT16 = 2
    INT16 = 3
    UINT32 = 4
    INT32 = 5
    FLOAT32 = 6
    BOOL = 7
    STRING = 8
    ARRAY = 9
    UINT64 = 10
    INT64 = 11
    FLOAT64 = 12


@dataclass(frozen=True)
class GgufKVParseResult:
    version: int
    tensor_count: int
    kv_count: int
    kv: Dict[str, Any]


def _read_exact(f, n: int) -> bytes:
    b = f.read(n)
    if b is None or len(b) != n:
        raise GgufKVParseError("Unexpected EOF while reading GGUF header")
    return b


def _u32(f) -> int:
    return struct.unpack("<I", _read_exact(f, 4))[0]


def _i32(f) -> int:
    return struct.unpack("<i", _read_exact(f, 4))[0]


def _u64(f) -> int:
    return struct.unpack("<Q", _read_exact(f, 8))[0]


def _i64(f) -> int:
    return struct.unpack("<q", _read_exact(f, 8))[0]


def _f32(f) -> float:
    return struct.unpack("<f", _read_exact(f, 4))[0]


def _f64(f) -> float:
    return struct.unpack("<d", _read_exact(f, 8))[0]


def _bool(f) -> bool:
    return struct.unpack("<?", _read_exact(f, 1))[0]


def _string(f) -> str:
    # GGUF strings are length-prefixed. In common implementations this is u64.
    # We enforce caps and reject absurd sizes.
    n = _u64(f)
    if n < 0:
        raise GgufKVParseError("Invalid GGUF string length")
    if n > _MAX_STRING_BYTES:
        raise GgufKVParseError(
            f"GGUF string too large ({n} bytes) — cap={_MAX_STRING_BYTES}"
        )
    raw = _read_exact(f, int(n))
    try:
        return raw.decode("utf-8", errors="strict")
    except Exception as e:
        raise GgufKVParseError(f"Invalid UTF-8 in GGUF string: {e}") from e


def _read_value(f, value_type: int) -> Any:
    if value_type == _ValueType.UINT8:
        return struct.unpack("<B", _read_exact(f, 1))[0]
    if value_type == _ValueType.INT8:
        return struct.unpack("<b", _read_exact(f, 1))[0]
    if value_type == _ValueType.UINT16:
        return struct.unpack("<H", _read_exact(f, 2))[0]
    if value_type == _ValueType.INT16:
        return struct.unpack("<h", _read_exact(f, 2))[0]
    if value_type == _ValueType.UINT32:
        return _u32(f)
    if value_type == _ValueType.INT32:
        return _i32(f)
    if value_type == _ValueType.UINT64:
        return _u64(f)
    if value_type == _ValueType.INT64:
        return _i64(f)
    if value_type == _ValueType.FLOAT32:
        return _f32(f)
    if value_type == _ValueType.FLOAT64:
        return _f64(f)
    if value_type == _ValueType.BOOL:
        return _bool(f)
    if value_type == _ValueType.STRING:
        return _string(f)
    if value_type == _ValueType.ARRAY:
        elem_type = _u32(f)
        if elem_type == _ValueType.ARRAY:
            raise GgufKVParseError("Nested GGUF arrays are not supported")
        count = _u64(f)
        if count > _MAX_ARRAY_ELEMENTS:
            raise GgufKVParseError(
                f"GGUF array too large ({count} elements) — cap={_MAX_ARRAY_ELEMENTS}"
            )
        out = []
        for _ in range(int(count)):
            out.append(_read_value(f, int(elem_type)))
        return out
    raise GgufKVParseError(f"Unsupported GGUF value type: {value_type}")


def parse_gguf_kv(path: str) -> GgufKVParseResult:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"GGUF file not found: {p}")

    with p.open("rb") as f:
        magic = _read_exact(f, 4)
        if magic != _GGUF_MAGIC:
            raise GgufKVParseError(f"Invalid GGUF magic: {magic!r}")

        version = _u32(f)
        tensor_count = _u64(f)
        kv_count = _u64(f)

        if kv_count > _MAX_KV_ENTRIES:
            raise GgufKVParseError(
                f"GGUF kv_count too large ({kv_count}) — cap={_MAX_KV_ENTRIES}"
            )

        kv: Dict[str, Any] = {}
        for _ in range(int(kv_count)):
            key = _string(f)
            value_type = _u32(f)
            value = _read_value(f, int(value_type))
            kv[key] = value

        return GgufKVParseResult(
            version=int(version),
            tensor_count=int(tensor_count),
            kv_count=int(kv_count),
            kv=kv,
        )
