"""Convert every car inside a PS3 IMG archive directly from a PC IMG.

No unpacking step: the PS3 archive (encrypted or not) is opened, each
``.ctd``/``.cft`` is rebuilt from the matching PC ``.wtd``/``.wft`` in
memory, and one write produces the finished archive.

Texture dicts (``.ctd``) are rebuilt with the game-faithful PS3 struct
(``wtd.convert_to_ctd``) — verified against retail files.  Meshes
(``.cft``) keep the experimental header re-wrap; pass ``textures_only=True``
to keep the retail PS3 mesh byte-for-byte (guaranteed to run in game) and
replace textures only.
"""

import os

from . import img as imgmod
from . import rsc as rscmod
from . import wft as wftmod
from . import wtd as wtdmod

_EXT_PAIRS = {".ctd": ".wtd", ".cft": ".wft"}

# Retail PS3 texture dicts decompress to at most ~1.4 MB.  Anything far
# above that (HD mods made for PC) can blow PS3 VRAM and black-screen the
# game at load, so converted dicts larger than this are skipped.
DEFAULT_MAX_DEC = 4 * 1024 * 1024


def fmt_size(n):
    if n >= 1024 * 1024:
        return "%.1f MB" % (n / (1024.0 * 1024))
    if n >= 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%d B" % n


def convert_archive(ps3_path, pc_path, out_path=None, textures_only=False,
                    only=None, backup=True, progress=None,
                    max_dec_bytes=DEFAULT_MAX_DEC):
    """Rebuild *ps3_path* using the PC sources in *pc_path*.

    Returns a report dict with per-file rows and size totals.  The archive
    is written atomically; a ``.bak`` copy is made first unless
    ``backup=False``.  ``progress(done, total, name)`` is called per file.
    Converted texture dicts whose decompressed size exceeds
    *max_dec_bytes* (None disables the check) are skipped and the retail
    PS3 file is kept instead.
    """
    if not os.path.isfile(ps3_path):
        raise ValueError("archive not found: %s" % ps3_path)
    if not os.path.isfile(pc_path):
        raise ValueError("PC archive not found: %s" % pc_path)
    only = {str(x).lower() for x in only} if only else None

    src = imgmod.ImgArchive(ps3_path)
    pc = imgmod.ImgArchive(pc_path)
    if not any(os.path.splitext(e.name)[1].lower() in _EXT_PAIRS
               for e in src.entries):
        raise ValueError(
            "PS3 archive contains no .ctd/.cft files - it looks like a PC "
            "IMG. Check which file you passed as the PS3 archive.")
    if not any(os.path.splitext(e.name)[1].lower()
               in tuple(_EXT_PAIRS.values()) for e in pc.entries):
        raise ValueError(
            "PC archive contains no .wtd/.wft files - it looks like a PS3 "
            "IMG. Check which file you passed as the PC source.")
    if out_path and os.path.normcase(os.path.abspath(out_path)) == \
            os.path.normcase(os.path.abspath(pc_path)):
        raise ValueError(
            "output path would overwrite the PC source archive - "
            "choose a different destination")
    rows = []
    replacements = {}
    todo = [e for e in src.entries
            if os.path.splitext(e.name)[1].lower() in _EXT_PAIRS
            and (only is None
                 or e.name.lower() in only
                 or os.path.splitext(e.name)[0].lower() in only)]
    if only is not None and not todo:
        raise ValueError(
            "none of the --only names matched a .ctd/.cft in the archive "
            "(example: admiral taxi)")
    done = 0
    for entry in todo:
        ext = os.path.splitext(entry.name)[1].lower()
        stem, _ = os.path.splitext(entry.name)
        before_raw = src.read(entry.name)
        before = len(before_raw)
        if ext == ".cft" and textures_only:
            rows.append({"name": entry.name, "kind": "mesh",
                         "before": before, "after": before,
                         "status": "kept-retail"})
            done += 1
            if progress:
                progress(done, len(todo), entry.name)
            continue
        pc_name = stem + _EXT_PAIRS[ext]
        if not pc.has(pc_name):
            rows.append({"name": entry.name,
                         "kind": "texture" if ext == ".ctd" else "mesh",
                         "before": before, "after": before,
                         "status": "no-pc-source"})
            done += 1
            if progress:
                progress(done, len(todo), entry.name)
            continue
        if ext == ".ctd":
            out_raw = wtdmod.convert_to_ctd(pc.read(pc_name))
            if max_dec_bytes:
                dec_len = len(
                    rscmod.RscFile.from_bytes(out_raw).decompressed)
                if dec_len > max_dec_bytes:
                    rows.append({"name": entry.name, "kind": "texture",
                                 "before": before, "after": before,
                                 "status": "skipped-too-big",
                                 "dec": dec_len})
                    done += 1
                    if progress:
                        progress(done, len(todo), entry.name)
                    continue
            status = "converted"
        else:
            out_raw = wftmod.WftFile.from_bytes(
                pc.read(pc_name), pc_name).to_ps3()
            status = "experimental"
        replacements[entry.name] = out_raw
        rows.append({"name": entry.name,
                     "kind": "texture" if ext == ".ctd" else "mesh",
                     "before": before, "after": len(out_raw),
                     "status": status})
        done += 1
        if progress:
            progress(done, len(todo), entry.name)

    if rows and not replacements:
        if all(r["status"] == "no-pc-source" for r in rows):
            raise ValueError(
                "none of the %d cars has a matching source in the PC "
                "archive - wrong PC file or different game version?"
                % len(rows))
        if all(r["status"] == "skipped-too-big" for r in rows):
            raise ValueError(
                "all %d texture dicts exceed the PS3 size limit - the PC "
                "archive looks HD-modded (keep the retail meshes and use "
                "a clean PC vehicles.img, or raise --max-dec-mb if you "
                "know what you are doing)" % len(rows))
    size_before = os.path.getsize(ps3_path)
    out_path = out_path or ps3_path
    written = False
    if replacements:
        if backup and out_path == ps3_path \
                and not os.path.exists(ps3_path + ".bak"):
            import shutil
            shutil.copy2(ps3_path, ps3_path + ".bak")
        imgmod.replace_entries(ps3_path, replacements=dict(replacements),
                               out_path=out_path)
        written = True
    size_after = os.path.getsize(out_path) if written else size_before

    converted = sum(1 for r in rows if r["status"] in
                    ("converted", "experimental"))
    return {
        "files": rows,
        "written": written,
        "converted": converted,
        "textures": sum(1 for r in rows if r["kind"] == "texture"
                        and r["status"] == "converted"),
        "meshes": sum(1 for r in rows if r["kind"] == "mesh"
                      and r["status"] == "experimental"),
        "kept": sum(1 for r in rows if r["status"].startswith("kept")
                    or r["status"] == "no-pc-source"),
        "skipped": sum(1 for r in rows if r["status"] == "skipped-too-big"),
        "size_before": size_before,
        "size_after": size_after,
        "out": out_path,
        "textures_only": bool(textures_only),
    }


_STATUS_AR = {
    "converted": "تم التحويل",
    "experimental": "مُحوَّل (مجسم تجريبي)",
    "kept-retail": "محفوظ (مجسم اللعبة الأصلي)",
    "no-pc-source": "محفوظ (لا يوجد ملف PC مطابق)",
    "skipped-too-big": "تم التخطي — كبير جداً على PS3 (يبقى نسيج اللعبة)",
}


def report_lines(rep):
    """Human-readable summary lines (with sizes) for the CLI."""
    _status_en = {
        "converted": "converted",
        "experimental": "converted (mesh experimental)",
        "kept-retail": "kept (retail PS3 mesh)",
        "no-pc-source": "kept (no PC source)",
        "skipped-too-big": "SKIPPED (too big for PS3, retail kept)",
    }
    lines = []
    for r in rep["files"]:
        if r["status"] == "kept-retail":
            continue
        if r["before"] == r["after"] and r["status"] in (
                "no-pc-source", "skipped-too-big"):
            arrow = ""
        else:
            arrow = "  %s -> %s" % (fmt_size(r["before"]),
                                    fmt_size(r["after"]))
        extra = ""
        if r["status"] == "skipped-too-big" and r.get("dec"):
            extra = " [dec %s]" % fmt_size(r["dec"])
        lines.append("%-24s %s%s%s" % (
            r["name"], _status_en.get(r["status"], r["status"]),
            arrow, extra))
    mode = ("[textures only]" if rep["textures_only"]
            else "[texture + mesh]")
    lines.append("-" * 56)
    lines.append("%s converted: %d (texture: %d, mesh: %d) | kept: %d"
                 " | skipped too big: %d"
                 % (mode, rep["converted"], rep["textures"], rep["meshes"],
                    rep["kept"], rep.get("skipped", 0)))
    lines.append("archive size: %s -> %s  (%+d bytes)"
                 % (fmt_size(rep["size_before"]), fmt_size(rep["size_after"]),
                    rep["size_after"] - rep["size_before"]))
    return lines
