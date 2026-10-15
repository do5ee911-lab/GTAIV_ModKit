import json
import os
import struct

from . import img as imgmod
from . import rpf as rpfmod


def parse_sfo(path):
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 20 or data[:4] != b"\x00PSF\x00"[:4] or data[1:4] != b"PSF":
        return {}
    _, version, key_start, data_start, count = struct.unpack_from("<4sIIII", data, 0)
    out = {}
    for i in range(count):
        off = 20 + i * 16
        if off + 16 > len(data):
            break
        key_off, fmt, dlen, dmax, doff = struct.unpack_from("<HHIII", data, off)
        key_end = data.find(b"\x00", key_start + key_off)
        key = data[key_start + key_off:key_end].decode("ascii", "replace")
        raw = data[data_start + doff:data_start + doff + dlen]
        if fmt in (0x0204, 0x0404, 0x0004):
            value = raw.split(b"\x00")[0].decode("utf-8", "replace") if fmt != 0x0004 else raw
        elif fmt == 0x0402:
            value = struct.unpack("<I", raw[:4])[0] if len(raw) >= 4 else 0
        else:
            value = raw.decode("utf-8", "replace")
        out[key] = value
    return out


def _archive_entries(r):
    entries = []
    for path in r.list_files():
        e = r.get(path)
        item = {
            "path": path,
            "size": e.size,
            "stored_size": e.stored_size,
            "resource": e.is_resource,
            "compressed": e.is_compressed,
        }
        head = r.stored_bytes(e)[:4]
        nested = _nested(head, r.stored_bytes(e), path)
        if nested:
            item["nested"] = nested
        entries.append(item)
    for path in r.list_dirs():
        entries.append({"path": path + "/", "dir": True})
    return entries


def _nested(head, blob, path):
    lower = path.lower()
    try:
        if head in (b"RPF2", b"RPF3") and lower.endswith(".rpf"):
            sub = rpfmod.RpfArchive.from_bytes(blob, path)
            return {"type": sub.kind.lower(), "count": sub.entry_count,
                    "files": _archive_entries(sub)}
        if lower.endswith(".img") and len(blob) >= 20:
            sub = imgmod.ImgArchive.from_bytes(blob, path)
            return {"type": "img3", "count": len(sub.entries),
                    "files": [{"path": e.name, "size": e.stored_size,
                               "resource": e.is_resource}
                              for e in sub.entries]}
    except Exception:
        return None
    return None


def _img_entries(a):
    out = []
    for e in a.entries:
        item = {"path": e.name, "size": e.stored_size, "resource": e.is_resource}
        blob = a.stored_bytes(e)
        nested = _nested(blob[:4], blob, e.name)
        if nested:
            item["nested"] = nested
        out.append(item)
    return out


def build_manifest(game_dir):
    manifest = {"game_dir": os.path.abspath(game_dir), "archives": {},
                "files": [], "sfo": {}}
    sfo_path = None
    for base, dirs, files in os.walk(game_dir):
        for fn in files:
            full = os.path.join(base, fn)
            rel = os.path.relpath(full, game_dir)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            manifest["files"].append({"path": rel.replace("\\", "/"), "size": size})
            if fn.upper() == "PARAM.SFO":
                sfo_path = full
            lower = fn.lower()
            if lower.endswith(".rpf") or lower.endswith(".img"):
                try:
                    if lower.endswith(".rpf"):
                        arc = rpfmod.RpfArchive(full)
                        manifest["archives"][rel.replace("\\", "/")] = {
                            "type": arc.kind.lower(), "size": size,
                            "entries": _archive_entries(arc)}
                    else:
                        arc = imgmod.ImgArchive(full)
                        manifest["archives"][rel.replace("\\", "/")] = {
                            "type": "img3", "size": size,
                            "entries": _img_entries(arc)}
                except Exception as exc:
                    manifest["archives"][rel.replace("\\", "/")] = {
                        "type": "error", "size": size, "error": str(exc)}
    if sfo_path:
        manifest["sfo"] = parse_sfo(sfo_path)
    manifest["files"].sort(key=lambda x: x["path"])
    return manifest


def write_manifest(game_dir, out_path):
    manifest = build_manifest(game_dir)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    return manifest
