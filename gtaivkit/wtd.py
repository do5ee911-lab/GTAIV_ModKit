import struct
import zlib

from .rsc import (MAGIC_PS3, RscError, TYPE_TEXTURE_PS3, encode_flags,
                  hash_name, make_ptr, pad_size_for_flags, ptr_offset,
                  swap_u32)
from . import tint as tintmod

DICT_MAGIC = 0xCCC36100
TEX_MAGIC = 0xEC896300
FORMAT_DXT5_FIELD = 0xAAE4
PS3_FMT_BYTES = {"DXT1": 0x86, "DXT3": 0x87, "DXT5": 0x88}
PS3_FMT_NAMES = {0x86: "DXT1", 0x87: "DXT3", 0x88: "DXT5"}


class Texture:
    __slots__ = ("name", "width", "height", "format", "mip_count",
                 "pixel_data", "hash")

    def __init__(self, name="", width=0, height=0, format="DXT5", mip_count=1,
                 pixel_data=None, tex_hash=0):
        self.name = name
        self.width = width
        self.height = height
        self.format = format
        self.mip_count = max(1, mip_count)
        self.pixel_data = pixel_data
        self.hash = tex_hash


def _read_u32(d, off, be):
    if off < 0 or off + 4 > len(d):
        return 0
    return struct.unpack_from(">I" if be else "<I", d, off)[0]


def _read_u16(d, off, be):
    if off < 0 or off + 2 > len(d):
        return 0
    return struct.unpack_from(">H" if be else "<H", d, off)[0]


def _read_string(d, ptr):
    off = ptr_offset(ptr)
    if off < 0 or off >= len(d):
        return ""
    end = d.find(b"\x00", off)
    if end < 0:
        end = len(d)
    return d[off:end].decode("latin-1")


def estimate_pixel_size(width, height, fmt, mips):
    if width <= 0 or height <= 0:
        return 0
    total = 0
    w, h = width, height
    for _ in range(max(1, mips)):
        bw = max(1, (w + 3) // 4)
        bh = max(1, (h + 3) // 4)
        block = 8 if (fmt or "").startswith("DXT1") else 16
        total += bw * bh * block
        if w <= 1 and h <= 1:
            break
        w = max(1, w // 2)
        h = max(1, h // 2)
    return total


def _guess_ps3_format(fmt_field):
    low = fmt_field & 0xFF
    if low in (228, 164) or (fmt_field & 0xFFFF) == FORMAT_DXT5_FIELD:
        return "DXT5"
    if low in (226, 162):
        return "DXT3"
    if low in (225, 161):
        return "DXT1"
    return "DXT5"


def count_mips(width, height, fmt, data_len):
    total = 0
    levels = 0
    w, h = width, height
    while True:
        bw = max(1, (w + 3) // 4)
        bh = max(1, (h + 3) // 4)
        block = 8 if (fmt or "").startswith("DXT1") else 16
        total += bw * bh * block
        levels += 1
        if total == data_len:
            return levels
        if total > data_len or (w <= 1 and h <= 1):
            return 0
        w = max(1, w // 2)
        h = max(1, h // 2)


def parse(dec, is_ps3, system_size=0):
    textures = []
    if len(dec) < 32:
        return textures
    be = is_ps3
    hash_ptr = _read_u32(dec, 16, be)
    hash_count = _read_u16(dec, 22, be)
    tex_ptr = _read_u32(dec, 24, be)
    tex_count = _read_u16(dec, 30, be)
    hash_off = ptr_offset(hash_ptr)
    tex_off = ptr_offset(tex_ptr)
    if hash_off < 0 or tex_off < 0 or tex_off + tex_count * 4 > len(dec):
        return textures
    hashes = []
    for i in range(max(0, hash_count)):
        if hash_off + i * 4 + 4 <= len(dec):
            hashes.append(_read_u32(dec, hash_off + i * 4, be))
    for i in range(tex_count):
        if tex_off + i * 4 + 4 > len(dec):
            break
        ptr = _read_u32(dec, tex_off + i * 4, be)
        off = ptr_offset(ptr)
        if off < 0 or off + 80 > len(dec):
            continue
        t = Texture()
        size = 0
        if is_ps3:
            t.name = _read_string(dec, _read_u32(dec, off + 44, True))
            t.width = _read_u16(dec, off + 28, True)
            t.height = _read_u16(dec, off + 30, True)
            fmtb = dec[off + 20]
            t.format = PS3_FMT_NAMES.get(fmtb) or _guess_ps3_format(
                _read_u32(dec, off + 24, True))
            t.mip_count = dec[off + 21] or 1
            size = struct.unpack_from("<I", dec, off + 16)[0]
            gpu_ptr = _read_u32(dec, off + 48, True)
        else:
            t.name = _read_string(dec, _read_u32(dec, off + 20, False))
            t.width = _read_u16(dec, off + 28, False)
            t.height = _read_u16(dec, off + 30, False)
            t.format = struct.unpack_from("4s", dec, off + 32)[0] \
                .rstrip(b"\x00").decode("latin-1") or "DXT5"
            t.mip_count = dec[off + 39] or 1
            gpu_ptr = _read_u32(dec, off + 72, False)
        t.hash = hashes[i] if i < len(hashes) else hash_name(t.name)
        gpu_off = ptr_offset(gpu_ptr)
        if is_ps3:
            if not size:
                size = estimate_pixel_size(t.width, t.height, t.format,
                                           t.mip_count)
            for base in (system_size + gpu_off, gpu_off):
                if base >= 0 and size > 0 and base + size <= len(dec):
                    t.pixel_data = dec[base:base + size]
                    break
        else:
            size = estimate_pixel_size(t.width, t.height, t.format,
                                       t.mip_count)
            if gpu_off >= 0 and gpu_off + size <= len(dec):
                t.pixel_data = dec[gpu_off:gpu_off + size]
        textures.append(t)
    return textures


def dxt1_base_to_dxt5(base, width, height):
    bw = max(1, (width + 3) // 4)
    bh = max(1, (height + 3) // 4)
    need = bw * bh * 8
    base = base[:need]
    out = bytearray(bw * bh * 16)
    opaque_alpha = bytes([255, 255, 0, 0, 0, 0, 0, 0])
    for i in range(bw * bh):
        chunk = base[i * 8:(i + 1) * 8]
        if len(chunk) < 8:
            break
        out[i * 16:i * 16 + 8] = opaque_alpha
        out[i * 16 + 8:i * 16 + 16] = chunk
    return bytes(out)


def to_ps3_texture(tex):
    fmt = tex.format or "DXT5"
    if fmt[:4] not in PS3_FMT_BYTES:
        fmt = "DXT5"
    mips = tex.mip_count
    if tex.pixel_data is not None:
        exact = count_mips(tex.width, tex.height, fmt, len(tex.pixel_data))
        if exact:
            mips = exact
    return Texture(tex.name, tex.width, tex.height, fmt, mips,
                   tex.pixel_data, tex.hash)


def build_ps3(textures):
    count = len(textures)
    pos = 32
    hash_off = pos
    pos += count * 4
    texptr_off = pos
    pos += count * 4
    struct_offs = []
    for _ in range(count):
        struct_offs.append(pos)
        pos += 80
    name_offs = []
    for t in textures:
        name_offs.append(pos)
        pos += len((t.name or "").encode("latin-1")) + 1
        while pos % 4 != 0:
            pos += 1
    while pos % 4096 != 0:
        pos += 1
    pos = pad_size_for_flags(pos)
    sys_size = pos
    gpu_cursor = 0
    gpu_offs = []
    for t in textures:
        gpu_offs.append(gpu_cursor)
        n = len(t.pixel_data) if t.pixel_data is not None else 0
        gpu_cursor += n
        while gpu_cursor % 256 != 0:
            gpu_cursor += 1
    gpu_cursor = pad_size_for_flags(gpu_cursor)
    gpu_size = gpu_cursor
    data = bytearray(sys_size + gpu_size)

    def w32(off, v):
        struct.pack_into(">I", data, off, v & 0xFFFFFFFF)

    def w16(off, v):
        struct.pack_into(">H", data, off, v & 0xFFFF)

    w32(0, DICT_MAGIC)
    w32(4, make_ptr(hash_off, 5))
    w32(8, 0)
    w32(12, 1)
    w32(16, make_ptr(hash_off, 5))
    w16(20, count)
    w16(22, count)
    w32(24, make_ptr(texptr_off, 5))
    w16(28, count)
    w16(30, count)
    for i, t in enumerate(textures):
        w32(hash_off + i * 4, t.hash if t.hash else hash_name(t.name))
        w32(texptr_off + i * 4, make_ptr(struct_offs[i], 5))
        so = struct_offs[i]
        px = t.pixel_data or b""
        fmtb = PS3_FMT_BYTES.get((t.format or "DXT5")[:4], 0x88)
        mips = count_mips(t.width, t.height, t.format, len(px)) \
            or max(1, t.mip_count)
        w32(so, TEX_MAGIC)
        w32(so + 8, 1)
        struct.pack_into("<I", data, so + 16, len(px))
        w32(so + 20, (fmtb << 24) | (mips << 16) | (2 << 8))
        w32(so + 24, FORMAT_DXT5_FIELD)
        w16(so + 28, t.width)
        w16(so + 30, t.height)
        w32(so + 32, 0x00010000)
        w32(so + 44, make_ptr(name_offs[i], 5))
        w32(so + 48, make_ptr(gpu_offs[i], 6))
        one = 0x3F800000
        w32(so + 52, one)
        w32(so + 56, one)
        w32(so + 60, one)
        name = (t.name or "").encode("latin-1")
        data[name_offs[i]:name_offs[i] + len(name)] = name
        if px:
            start = sys_size + gpu_offs[i]
            data[start:start + len(px)] = px
    return bytes(data), sys_size, gpu_size


def convert_to_ctd(wtd_bytes):
    from .rsc import RscFile
    rsc = RscFile.from_bytes(wtd_bytes)
    textures = parse(rsc.decompressed, rsc.is_ps3, rsc.system_size)
    if not textures:
        raise RscError("no textures found in WTD")
    ps3_tex = [to_ps3_texture(t) for t in textures]
    data, sys_size, gpu_size = build_ps3(ps3_tex)
    flags = encode_flags(sys_size, gpu_size)
    blob = zlib.compress(data, 9)
    return MAGIC_PS3 + struct.pack(">II", TYPE_TEXTURE_PS3, flags) + blob


def dds_export(tex):
    import struct as st
    px = tex.pixel_data or b""
    mips = max(1, tex.mip_count)
    fourcc = {"DXT1": 0x31545844, "DXT3": 0x33545844}.get(
        (tex.format or "DXT5")[:4], 0x35545844)
    out = bytearray()
    out += st.pack("<I", 0x20534444)
    out += st.pack("<I", 124)
    out += st.pack("<I", 0x81007)
    out += st.pack("<IIII", tex.height, tex.width, len(px), 0)
    out += st.pack("<I", mips)
    out += b"\x00" * 44
    out += st.pack("<II", 32, 4)
    out += st.pack("<I", fourcc)
    out += st.pack("<IIIII", 0, 0, 0, 0, 0)
    out += st.pack("<IIIII", 4096, 0, 0, 0, 0)
    if len(out) != 128:
        raise ValueError("bad DDS header size: %d" % len(out))
    out += px
    return bytes(out)
