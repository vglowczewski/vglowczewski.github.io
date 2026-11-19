"""Small, dependency-free WebP container validator for build-time checks."""
from pathlib import Path


def webp_info(path, metadata_free=False):
    path = Path(path)
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP" or len(data) < 26:
        raise ValueError(f"{path.name}: invalid WebP container")
    if int.from_bytes(data[4:8], "little") + 8 != len(data):
        raise ValueError(f"{path.name}: invalid RIFF size")
    dimensions, alpha, chunks = None, False, []
    offset = 12
    while offset + 8 <= len(data):
        kind, size = data[offset:offset + 4], int.from_bytes(data[offset + 4:offset + 8], "little")
        content = data[offset + 8:offset + 8 + size]
        if len(content) != size:
            raise ValueError(f"{path.name}: truncated WebP chunk")
        chunks.append(kind)
        if metadata_free and kind not in {b"VP8 ", b"VP8L", b"VP8X", b"ALPH"}:
            raise ValueError(f"{path.name}: metadata or unsupported chunk {kind!r}")
        if kind == b"VP8X" and size >= 10:
            dimensions = tuple(int.from_bytes(content[i:i + 3], "little") + 1 for i in (4, 7))
            alpha = bool(content[0] & 16)
            if metadata_free and content[0] & (32 | 8 | 4 | 2):
                raise ValueError(f"{path.name}: metadata/animation flags")
        elif kind == b"VP8L" and size >= 5 and content[0] == 0x2f:
            bits = int.from_bytes(content[1:5], "little")
            dimensions = ((bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1)
            alpha = alpha or bool(bits & (1 << 28))
        elif kind == b"VP8 " and size >= 10 and content[3:6] == b"\x9d\x01\x2a":
            dimensions = tuple(int.from_bytes(content[i:i + 2], "little") & 0x3fff for i in (6, 8))
        elif kind == b"ALPH":
            alpha = True
        offset += 8 + size + (size % 2)
    if offset != len(data) or dimensions is None:
        raise ValueError(f"{path.name}: incomplete WebP data")
    return {"width": dimensions[0], "height": dimensions[1], "alpha": alpha, "chunks": chunks}
