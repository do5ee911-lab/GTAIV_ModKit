import struct

TINT_SHADER_RENAME = {
    "texturesampler": "ragex_tint",
    "dirtsampler": "ragex_tint_zero",
    "specsampler": "ragex_tint_zero",
}

GLASS_PARTS_EXACT = {"windscreen", "windscreen_r", "window_lf", "window_rf",
                     "window_lr", "window_rr", "window_lm", "window_rm"}

DOOR_PREFIXES = ("misc_", "door_")
DOOR_EXACT = {"boot"}

WINDOW_KEYWORDS = ("window",)
GLASS_KEYWORDS = ("glass", "window")


def fnv_shader_hash(name):
    h = 0
    for c in (name or "").lower():
        h = (ord(c) + h) * 0x401
        h &= 0xFFFFFFFF
        h ^= h >> 6
        h = h * 9
        h &= 0xFFFFFFFF
        h ^= h >> 11
        h = h * 0x8001
        h &= 0xFFFFFFFF
    return h


def make_tint_ptr(offset):
    return (offset & 0x0FFFFFFF) | 0x50000000


def ptr_tag(ptr):
    return (ptr >> 28) & 0xF


def ptr_off(ptr):
    return ptr & 0x0FFFFFFF


def classify_part(name):
    low = (name or "").lower()
    if low in GLASS_PARTS_EXACT:
        return "glass"
    if low.startswith("misc_") or low.startswith("door_") or low == "boot":
        return "door"
    if any(kw in low for kw in WINDOW_KEYWORDS):
        return "window"
    if any(kw in low for kw in GLASS_KEYWORDS):
        return "glass"
    return "body"


def get_shader_replacement(name):
    low = (name or "").lower()
    return TINT_SHADER_RENAME.get(low)


def inject_tint_params(dec, shader_offset, tint_color=(1.0, 1.0, 1.0, 1.0)):
    if shader_offset < 0 or shader_offset + 0x20 > len(dec):
        return False
    r, g, b, a = tint_color
    struct.pack_into("<ffff", dec, shader_offset + 0x04, r, g, b, a)
    return True


def patch_shader_names(dec, start, end):
    renamed = []
    pos = start
    while pos + 0x60 <= end:
        name_ptr = struct.unpack_from("<I", dec, pos + 0x14)[0]
        if ptr_tag(name_ptr) == 5:
            name_off = ptr_off(name_ptr)
            if name_off < len(dec):
                end_idx = dec.find(b"\x00", name_off)
                if end_idx < 0:
                    end_idx = min(name_off + 32, len(dec))
                name = dec[name_off:end_idx].decode("latin-1", errors="ignore")
                replacement = get_shader_replacement(name)
                if replacement:
                    rep_bytes = replacement.encode("latin-1") + b"\x00"
                    dec[name_off:name_off + len(rep_bytes)] = rep_bytes
                    renamed.append((name, replacement))
        pos += 0x60
    return renamed


def classify_drawables(dec, drawable_table_off, drawable_count):
    results = {"glass": [], "door": [], "window": [], "body": []}
    for i in range(drawable_count):
        entry_off = drawable_table_off + i * 0xE0
        if entry_off + 0x20 > len(dec):
            break
        name_ptr = struct.unpack_from("<I", dec, entry_off + 0x14)[0]
        if ptr_tag(name_ptr) == 5:
            name_off = ptr_off(name_ptr)
            if name_off < len(dec):
                end_idx = dec.find(b"\x00", name_off)
                if end_idx < 0:
                    end_idx = min(name_off + 64, len(dec))
                name = dec[name_off:end_idx].decode("latin-1", errors="ignore")
                cat = classify_part(name)
                results[cat].append((i, name))
    return results


def tintColorToBytes(tint):
    r, g, b, a = tint
    return struct.pack("<I", int(r * 255) & 0xFF) + \
           struct.pack("<I", int(g * 255) & 0xFF) + \
           struct.pack("<I", int(b * 255) & 0xFF) + \
           struct.pack("<I", int(a * 255) & 0xFF)
