import os
import shutil

from . import img as imgmod
from . import rpf as rpfmod


def open_archive(path):
    with open(path, "rb") as fh:
        head = fh.read(4)
    if head in (b"RPF2", b"RPF3"):
        return rpfmod.RpfArchive(path)
    try:
        return imgmod.ImgArchive(path)
    except imgmod.ImgError as exc:
        raise ValueError("not an RPF2/RPF3 or IMG3 archive: %s" % exc)


def _paths(arc):
    if isinstance(arc, rpfmod.RpfArchive):
        return list(arc.list_files())
    return [e.name for e in arc.entries]


def scan(arc, folder):
    reps = {}
    unchanged = 0
    known = set()
    total = 0
    for inner in _paths(arc):
        total += 1
        known.add(inner.lower())
        disk = os.path.join(folder, *inner.split("/"))
        if not os.path.isfile(disk):
            continue
        with open(disk, "rb") as fh:
            blob = fh.read()
        entry = arc.get(inner)
        is_res = blob[:4] in rpfmod.RSC_MAGICS
        if bool(entry.is_resource) != is_res:
            raise ValueError(
                "resource/plain type mismatch for: %s" % inner)
        if blob == arc.read(inner):
            unchanged += 1
        else:
            reps[inner] = blob
    unknown = []
    for root, _dirs, files in os.walk(folder):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, folder)
            if rel.lower().endswith((".bak", ".tmp")):
                continue
            inner = rel.replace(os.sep, "/")
            if inner.lower() not in known:
                unknown.append(inner)
    return {"replacements": reps, "unknown": sorted(unknown),
            "unchanged": unchanged, "total": total}


def rebuild(path, folder, out_path=None, add=False, backup=True):
    if not os.path.isdir(folder):
        raise ValueError("folder not found: %s" % folder)
    arc = open_archive(path)
    res = scan(arc, folder)
    is_img = isinstance(arc, imgmod.ImgArchive)
    unknown = res["unknown"]
    if unknown and not add:
        raise ValueError(
            "files in folder are not present in the archive: %s"
            % ", ".join(unknown[:5]) + (" ..." if len(unknown) > 5 else ""))
    if unknown and not is_img:
        raise ValueError("adding new files is only supported for IMG archives")
    additions = None
    if unknown:
        additions = {}
        for inner in unknown:
            with open(os.path.join(folder, *inner.split("/")), "rb") as fh:
                additions[inner] = fh.read()
    reps = res["replacements"]
    if not reps and not additions:
        return {"changed": [], "added": [], "unchanged": res["unchanged"],
                "total": res["total"], "written": False, "out": path}
    changed = sorted(reps)
    added = sorted(additions or {})
    if backup and out_path in (None, path) \
            and not os.path.exists(path + ".bak"):
        shutil.copy2(path, path + ".bak")
    if is_img:
        imgmod.replace_entries(path, replacements=dict(reps),
                               additions=dict(additions) if additions else None,
                               out_path=out_path)
    else:
        rpfmod.replace_files(path, dict(reps), out_path=out_path)
    return {"changed": changed, "added": added,
            "unchanged": res["unchanged"], "total": res["total"],
            "written": True, "out": out_path or path}
