import argparse
import hashlib
import json
import os
import shutil
import sys

from . import aes
from . import batch as batchmod
from . import cars as carsmod
from . import img as imgmod
from . import manifest as manifestmod
from . import rebuild as rebuildmod
from . import rpf as rpfmod
from . import rgxa as rgxamod
from . import rsc as rscmod
from . import tint as tintmod
from . import wft as wftmod
from . import wtd as wtdmod

DEFAULT_GAME = r"C:\Users\_MO\Desktop\13\PS3_GAME\USRDIR"
VERSION = "2.0.0"


def open_archive(path):
    with open(path, "rb") as fh:
        head = fh.read(4)
    if head in (b"RPF2", b"RPF3"):
        return rpfmod.RpfArchive(path)
    try:
        return imgmod.ImgArchive(path)
    except imgmod.ImgError as exc:
        raise SystemExit(
            "error: %s is neither an RPF2/RPF3 archive nor an IMG3 image "
            "(%s)" % (path, exc))


def backup_path(path):
    return path + ".bak"


def maybe_backup(path, enabled):
    if enabled and not os.path.exists(backup_path(path)):
        shutil.copy2(path, backup_path(path))


def _archive_name(a):
    return getattr(a, "path", "<memory>")


def _iter_files(a):
    if isinstance(a, rpfmod.RpfArchive):
        for p in a.list_files():
            yield p, a.get(p)
    else:
        for e in a.entries:
            yield e.name, e


def _is_resource(a, e):
    return e.is_resource


def _read(a, e):
    if isinstance(a, rpfmod.RpfArchive):
        return a.read_entry(e)
    return a.stored_bytes(e)


def _stored(a, e):
    if isinstance(a, rpfmod.RpfArchive):
        return a.stored_bytes(e)
    return a.stored_bytes(e)


def cmd_key(args):
    print("KEY     =", aes.KEY_HEX)
    print("SHA1    =", aes.KEY_SHA1)
    if args.check:
        if os.path.isfile(args.check):
            with open(args.check, "rb") as fh:
                data = fh.read()
            ok = aes.KEY in data
            detail = "key bytes found in file" if ok else "key bytes NOT found in file"
        else:
            try:
                key = bytes.fromhex(args.check.strip())
            except ValueError:
                raise SystemExit("error: --check expects a file path or hex key")
            ok = hashlib.sha1(key).hexdigest().upper() == aes.KEY_SHA1
            detail = "hex key matches" if ok else "hex key does not match"
        print("CHECK   =", "OK" if ok else "MISMATCH", "-", detail)
        if not ok:
            raise SystemExit(1)


def cmd_list(args):
    a = open_archive(args.archive)
    print("%s: %s, %d entries" % (_archive_name(a),
                                  getattr(a, "kind", "?"),
                                  a.entry_count if isinstance(a, rpfmod.RpfArchive) else len(a.entries)))
    files = sorted(_iter_files(a), key=lambda x: x[0])
    total = 0
    for path, e in files:
        flags = []
        if _is_resource(a, e):
            flags.append("RSC")
        elif isinstance(a, rpfmod.RpfArchive) and e.is_compressed:
            flags.append("deflate")
        size = e.size if isinstance(a, rpfmod.RpfArchive) and not e.is_resource else e.stored_size
        if isinstance(a, rpfmod.RpfArchive) and e.is_resource:
            size = e.stored_size
        total += size
        print("%10d  %-6s  %s" % (size, ",".join(flags), path))
    print("-- %d files, %d bytes (uncompressed where known)" % (len(files), total))
    if args.recursive:
        for path, e in list(files):
            if not _is_resource(a, e):
                continue
            blob = _stored(a, e)
            if blob[:4] in (b"RPF2", b"RPF3") and path.lower().endswith(".rpf"):
                print("== nested %s ==" % path)
                cmd_list_data(rpfmod.RpfArchive.from_bytes(blob, path))
            elif len(blob) >= 16:
                try:
                    sub = imgmod.ImgArchive.from_bytes(blob, path)
                    if sub.ident == imgmod.IMG_MAGIC and path.lower().endswith(".img"):
                        print("== nested %s ==" % path)
                        cmd_list_data(sub)
                except Exception:
                    pass


def cmd_list_data(a):
    for path, e in sorted(_iter_files(a), key=lambda x: x[0]):
        print("%10d  %-6s  %s" % (e.stored_size,
                                  "RSC" if _is_resource(a, e) else "",
                                  path))


def cmd_extract(args):
    a = open_archive(args.archive)
    outdir = args.out
    wanted = set(p.lstrip("/") for p in args.paths) if args.paths else None
    count = 0
    for path, e in _iter_files(a):
        if wanted is not None and path not in wanted:
            continue
        blob = _stored(a, e) if args.raw else _read(a, e)
        target = os.path.join(outdir, path.replace("/", os.sep))
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(blob)
        count += 1
    if wanted is not None:
        missing = wanted - {p for p, _ in _iter_files(a)}
        if missing:
            raise SystemExit("error: not in archive: %s" % ", ".join(sorted(missing)))
    print("extracted %d file(s) to %s" % (count, outdir))


def cmd_verify(args):
    failed = 0
    for path in args.archives:
        try:
            a = open_archive(path)
            n = 0
            for _, e in _iter_files(a):
                blob = _read(a, e)
                if isinstance(a, rpfmod.RpfArchive) and not e.is_resource:
                    if len(blob) != e.size:
                        raise rpfmod.RpfError("size mismatch for %s" % getattr(e, "path", "?"))
                n += 1
                if blob[:4] in (b"RPF2", b"RPF3") and str(getattr(e, "path", "")).lower().endswith(".rpf"):
                    rpfmod.RpfArchive.from_bytes(blob, path)
                elif len(blob) >= 16 and str(getattr(e, "name", getattr(e, "path", ""))).lower().endswith(".img"):
                    try:
                        imgmod.ImgArchive.from_bytes(blob, path)
                    except Exception:
                        pass
            print("OK   %s (%d entries)" % (path, n))
        except Exception as exc:
            failed += 1
            print("FAIL %s: %s" % (path, exc))
    if failed:
        raise SystemExit(1)


def cmd_inject(args):
    a = open_archive(args.archive)
    with open(args.file, "rb") as fh:
        blob = fh.read()
    inner = args.inner.lstrip("/")
    if isinstance(a, rpfmod.RpfArchive):
        if args.add:
            raise SystemExit(
                "error: adding new files to RPF archives is not supported; "
                "replace an existing path instead")
        if not a.has(inner):
            raise SystemExit("error: no such path in archive: %s (use 'list')" % inner)
        maybe_backup(args.archive, not args.no_backup)
        rpfmod.replace_files(args.archive, {inner: blob}, out_path=args.out)
        print("replaced %s in %s" % (inner, args.archive))
    else:
        if a.has(inner):
            reps = {inner: blob}
            adds = None
        elif args.add:
            reps = None
            adds = {inner: blob}
        else:
            raise SystemExit("error: no such entry: %s (use --add)" % inner)
        maybe_backup(args.archive, not args.no_backup)
        imgmod.replace_entries(args.archive, replacements=reps, additions=adds,
                               out_path=args.out)
        print("%s %s in %s" % ("added" if adds else "replaced", inner, args.archive))


def cmd_rebuild(args):
    try:
        stats = rebuildmod.rebuild(args.archive, args.folder,
                                   out_path=args.out, add=args.add,
                                   backup=not args.no_backup)
    except ValueError as exc:
        raise SystemExit("error: %s" % exc)
    if not stats["written"]:
        print("no changes: %s already matches %s (nothing written)"
              % (args.archive, args.folder))
        return
    print("rebuilt %s -> %s" % (args.archive, stats["out"]))
    print("  replaced : %d" % len(stats["changed"]))
    print("  added    : %d" % len(stats["added"]))
    print("  unchanged: %d / %d" % (stats["unchanged"], stats["total"]))
    for name in stats["changed"][:20]:
        print("    ~ %s" % name)
    if len(stats["changed"]) > 20:
        print("    ... %d more" % (len(stats["changed"]) - 20))
    for name in stats["added"]:
        print("    + %s" % name)


def cmd_manifest(args):
    out = args.out or "manifest.json"
    m = manifestmod.write_manifest(args.game, out)
    print("wrote %s: %d archives, %d loose files" %
          (out, len(m["archives"]), len(m["files"])))
    sfo = m.get("sfo") or {}
    if sfo.get("TITLE"):
        print("game: %s [%s]" % (sfo.get("TITLE"), sfo.get("TITLE_ID")))


def cmd_cars_list(args):
    img = args.img or carsmod.default_img(args.game)
    cars = carsmod.list_cars(img)
    for model in sorted(cars):
        parts = cars[model]
        print("%-20s %s" % (model, " ".join(
            "%s(%d)" % (k, v) for k, v in sorted(parts.items()))))
    print("-- %d models in %s" % (len(cars), img))


def cmd_cars_extract(args):
    img = args.img or carsmod.default_img(args.game)
    written = carsmod.extract_car(img, args.model, args.out)
    print("extracted %s: %s" % (args.model, ", ".join(written)))


def cmd_cars_install(args):
    img = args.img or carsmod.default_img(args.game)
    out, replaced, skipped = carsmod.install_folder(
        img, args.folder, out_path=args.out, backup=not args.no_backup)
    print("updated %s: %d file(s) replaced" % (out, len(replaced)))
    for name in replaced:
        print("  %s" % name)
    for fn in skipped:
        print("  skipped (no such model): %s" % fn)


def cmd_cars_replace(args):
    img = args.img or carsmod.default_img(args.game)
    out = carsmod.replace_car(img, args.model, ctd_path=args.ctd,
                              cft_path=args.cft, out_path=args.out,
                              backup=not args.no_backup)
    print("updated %s" % out)


def _load_rsc_any(path):
    with open(path, "rb") as fh:
        data = fh.read()
    return rscmod.RscFile.from_bytes(data, path)


def cmd_inspect(args):
    rsc = _load_rsc_any(args.file)
    print("File: %s" % args.file)
    print("Platform: %s" % ("PS3" if rsc.is_ps3 else "PC"))
    print("Type: %d (0x%X)" % (rsc.type, rsc.type))
    print("Flags: 0x%08X" % rsc.flags)
    print("SystemSize: %d" % rsc.system_size)
    print("GpuSize: %d" % rsc.gpu_size)
    print("Decompressed: %d" % len(rsc.decompressed))
    try:
        textures = wtdmod.parse(rsc.decompressed, rsc.is_ps3, rsc.system_size)
    except Exception:
        textures = []
    print("Textures: %d" % len(textures))
    for t in textures:
        px = len(t.pixel_data) if t.pixel_data else 0
        print("  %s  %dx%d  %s  %d" % (t.name, t.width, t.height, t.format, px))


def cmd_tex(args):
    rsc = _load_rsc_any(args.file)
    textures = wtdmod.parse(rsc.decompressed, rsc.is_ps3, rsc.system_size)
    if not textures:
        raise SystemExit("error: no textures in %s" % args.file)
    os.makedirs(args.out, exist_ok=True)
    count = 0
    used = set()
    for i, t in enumerate(textures):
        if t.pixel_data is None:
            continue
        stem = os.path.splitext(os.path.basename(t.name or ""))[0] or ("tex_%d" % i)
        for ch in '\\/:*?"<>|':
            stem = stem.replace(ch, "_")
        base = stem
        n = 1
        while stem.lower() in used:
            stem = "%s_%d" % (base, n)
            n += 1
        used.add(stem.lower())
        out = os.path.join(args.out, stem + ".dds")
        with open(out, "wb") as fh:
            fh.write(wtdmod.dds_export(t))
        count += 1
    print("extracted %d DDS to %s" % (count, args.out))


def cmd_convert(args):
    lower_in = args.input.lower()
    lower_out = args.output.lower()
    if lower_in.endswith(".wtd") and lower_out.endswith(".ctd"):
        with open(args.input, "rb") as fh:
            ctd = wtdmod.convert_to_ctd(fh.read())
        with open(args.output, "wb") as fh:
            fh.write(ctd)
        rsc = rscmod.RscFile.from_bytes(ctd, args.output)
        print("OK: %s -> %s (%d bytes, %d textures, sys=%d gpu=%d)" %
              (args.input, args.output, len(ctd),
               len(wtdmod.parse(rsc.decompressed, True, rsc.system_size)),
               rsc.system_size, rsc.gpu_size))
    elif lower_in.endswith(".wft") and lower_out.endswith(".cft"):
        wft = wftmod.WftFile.load(args.input)
        cft = wft.to_ps3()
        with open(args.output, "wb") as fh:
            fh.write(cft)
        print("OK (experimental re-wrap): %s -> %s (%d bytes, sys=%d gpu=%d)" %
              (args.input, args.output, len(cft),
               wft.system_size, wft.gpu_size))
        print("note: internal model layout is kept from PC; verify on hardware")
    else:
        raise SystemExit(
            "error: supported pairs: .wtd->.ctd, .wft->.cft "
            "(got %s -> %s)" % (args.input, args.output))


def cmd_convert_archive(args):
    def progress(done, total, name):
        print("  [%d/%d] %s" % (done, total, name))
    try:
        rep = batchmod.convert_archive(
            args.archive, args.pc, out_path=args.out,
            textures_only=args.textures_only, only=args.only,
            backup=not args.no_backup, progress=progress,
            max_dec_bytes=(int(args.max_dec_mb * 1024 * 1024)
                           if args.max_dec_mb > 0 else None))
    except ValueError as exc:
        raise SystemExit("error: %s" % exc)
    for line in batchmod.report_lines(rep):
        print(line)
    if not rep["written"]:
        raise SystemExit("error: nothing converted (no matching PC sources)")


def cmd_rgxa_pack(args):
    with open(args.input, "rb") as fh:
        raw = fh.read()
    packed = rgxamod.pack_rgxa(raw)
    with open(args.output, "wb") as fh:
        fh.write(packed)
    print("packed %s -> %s (%d bytes, raw %d)" %
          (args.input, args.output, len(packed), len(raw)))


def cmd_rgxa_unpack(args):
    with open(args.input, "rb") as fh:
        data = fh.read()
    raw = rgxamod.unpack_rgxa(data)
    with open(args.output, "wb") as fh:
        fh.write(raw)
    print("unpacked %s -> %s (%d bytes, packed %d)" %
          (args.input, args.output, len(raw), len(data)))


def cmd_tint_hash(args):
    h = tintmod.fnv_shader_hash(args.name)
    print("shader hash for %r: 0x%08X (%d)" % (args.name, h, h))


def cmd_tint_inject(args):
    wft = wftmod.WftFile.load(args.input)
    tint = tuple(args.color) if args.color else (1.0, 1.0, 1.0, 1.0)
    result = wft.inject_tint(tint)
    cft = wft.to_ps3()
    with open(args.output, "wb") as fh:
        fh.write(cft)
    print("injected tint into %s -> %s" % (args.input, args.output))
    print("  shader renames: %d" % len(result["renamed"]))
    for old, new in result["renamed"]:
        print("    %s -> %s" % (old, new))
    print("  tints patched: %d" % result["patched"])


def cmd_tint_classify(args):
    with open(args.input, "rb") as fh:
        data = fh.read()
    rsc = rscmod.RscFile.from_bytes(data, args.input)
    dec = rsc.decompressed
    if len(dec) < 0x70:
        raise SystemExit("error: WFT too small")
    header_size = struct.unpack_from("<I", dec, 0x00)[0]
    drawable_table_off = struct.unpack_from("<I", dec, 0x14)[0] & 0x0FFFFFFF
    drawable_count = struct.unpack_from("<I", dec, 0x18)[0]
    if drawable_count > 0x100:
        raise SystemExit("error: bad drawable count %d" % drawable_count)
    cats = tintmod.classify_drawables(dec, drawable_table_off, drawable_count)
    print("classified %d drawables in %s:" % (drawable_count, args.input))
    for cat, items in cats.items():
        if items:
            print("  %s (%d):" % (cat, len(items)))
            for idx, name in items:
                print("    [%d] %s" % (idx, name))


def build_parser():
    p = argparse.ArgumentParser(prog="gtaivkit",
                                description="GTA IV PS3 archive toolkit v%s" % VERSION)
    p.add_argument("--game", default=DEFAULT_GAME,
                   help="path to USRDIR (default: %(default)s)")
    p.add_argument("--version", action="version", version="gtaivkit %s" % VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)

    k = sub.add_parser("key", help="show the extracted AES key")
    k.add_argument("--check", help="verify key against a GTAIV.exe copy")
    k.set_defaults(fn=cmd_key)

    ls = sub.add_parser("list", help="list archive contents")
    ls.add_argument("archive")
    ls.add_argument("-r", "--recursive", action="store_true",
                    help="also list nested archives")
    ls.set_defaults(fn=cmd_list)

    ex = sub.add_parser("extract", help="extract files from an archive")
    ex.add_argument("archive")
    ex.add_argument("paths", nargs="*", help="inner paths (default: all)")
    ex.add_argument("-o", "--out", default="extracted", help="output directory")
    ex.add_argument("--raw", action="store_true",
                    help="store verbatim archive bytes (no decompression)")
    ex.set_defaults(fn=cmd_extract)

    ij = sub.add_parser("inject", help="replace (or add) one file in an archive")
    ij.add_argument("archive")
    ij.add_argument("file", help="local file to inject")
    ij.add_argument("inner", help="path inside the archive")
    ij.add_argument("--add", action="store_true", help="allow adding a new entry (IMG only)")
    ij.add_argument("--out", help="write to a different output file")
    ij.add_argument("--no-backup", action="store_true")
    ij.set_defaults(fn=cmd_inject)

    rb = sub.add_parser("rebuild",
                        help="rebuild an archive from an extracted folder")
    rb.add_argument("archive")
    rb.add_argument("folder", help="folder previously written by 'extract'")
    rb.add_argument("-o", "--out", help="write to a different output file")
    rb.add_argument("--add", action="store_true",
                    help="also add files missing from the archive (IMG only)")
    rb.add_argument("--no-backup", action="store_true")
    rb.set_defaults(fn=cmd_rebuild)

    vf = sub.add_parser("verify", help="read every entry of archives to check integrity")
    vf.add_argument("archives", nargs="+")
    vf.set_defaults(fn=cmd_verify)

    mf = sub.add_parser("manifest", help="index every file in the game directory")
    mf.add_argument("-o", "--out", default="manifest.json")
    mf.set_defaults(fn=cmd_manifest)

    cr = sub.add_parser("cars", help="vehicle images (.ctd/.cft) helpers")
    crsub = cr.add_subparsers(dest="cars_cmd", required=True)
    cl = crsub.add_parser("list", help="list models in vehicles.img")
    cl.add_argument("--img", help="vehicles.img path")
    cl.set_defaults(fn=cmd_cars_list)
    cp = crsub.add_parser("replace", help="replace one vehicle")
    cp.add_argument("model", help="model name, e.g. admiral")
    cp.add_argument("--ctd", help="PS3 .ctd file (DFF/WTD converted)")
    cp.add_argument("--cft", help="PS3 .cft file")
    cp.add_argument("--img", help="vehicles.img path")
    cp.add_argument("--out", help="write to a different output file")
    cp.add_argument("--no-backup", action="store_true")
    cp.set_defaults(fn=cmd_cars_replace)
    ce = crsub.add_parser("extract", help="extract one vehicle (.ctd/.cft)")
    ce.add_argument("model", help="model name, e.g. admiral")
    ce.add_argument("-o", "--out", default=".", help="output directory")
    ce.add_argument("--img", help="vehicles.img path")
    ce.set_defaults(fn=cmd_cars_extract)
    ci = crsub.add_parser("install",
                          help="replace every vehicle found in a folder of .ctd/.cft mods")
    ci.add_argument("folder", help="folder containing mod .ctd/.cft files")
    ci.add_argument("--img", help="vehicles.img path")
    ci.add_argument("--out", help="write to a different output file")
    ci.add_argument("--no-backup", action="store_true")
    ci.set_defaults(fn=cmd_cars_install)

    ins = sub.add_parser("inspect", help="show RSC info of a WFT/WTD/CFT/CTD")
    ins.add_argument("file")
    ins.set_defaults(fn=cmd_inspect)

    tx = sub.add_parser("tex", help="extract textures from WTD/CTD as DDS")
    tx.add_argument("file")
    tx.add_argument("-o", "--out", default="textures", help="output directory")
    tx.set_defaults(fn=cmd_tex)

    cv = sub.add_parser("convert", help="convert PC asset to PS3 (wtd->ctd, wft->cft)")
    cv.add_argument("input")
    cv.add_argument("output")
    cv.set_defaults(fn=cmd_convert)

    ca = sub.add_parser(
        "convert-archive",
        help="convert every car inside a PS3 IMG directly from a PC IMG "
             "(no unpacking)")
    ca.add_argument("archive", help="PS3 vehicles.img (encrypted or not)")
    ca.add_argument("--pc", required=True, help="PC vehicles.img with sources")
    ca.add_argument("-o", "--out",
                    help="write to a different file (default: in place)")
    ca.add_argument("--textures-only", action="store_true",
                    help="keep retail PS3 meshes; convert textures only "
                         "(guaranteed to run in game)")
    ca.add_argument("--only", nargs="*",
                    help="car names to convert (default: all)")
    ca.add_argument("--max-dec-mb", type=float, default=4.0, metavar="MB",
                    help="skip texture dicts whose decompressed size "
                         "exceeds this many MB (default: 4; 0 = no limit). "
                         "Guards against HD mods that black-screen the PS3")
    ca.add_argument("--no-backup", action="store_true")
    ca.set_defaults(fn=cmd_convert_archive)

    rg = sub.add_parser("rgxa", help="RGXA resource pack/unpack")
    rgsub = rg.add_subparsers(dest="rgxa_cmd", required=True)
    rgp = rgsub.add_parser("pack", help="pack raw data into RGXA")
    rgp.add_argument("input")
    rgp.add_argument("output")
    rgp.set_defaults(fn=cmd_rgxa_pack)
    rgu = rgsub.add_parser("unpack", help="unpack RGXA to raw data")
    rgu.add_argument("input")
    rgu.add_argument("output")
    rgu.set_defaults(fn=cmd_rgxa_unpack)

    tn = sub.add_parser("tint", help="shader tint injection tools")
    tnsub = tn.add_subparsers(dest="tint_cmd", required=True)
    th = tnsub.add_parser("hash", help="compute shader name hash")
    th.add_argument("name")
    th.set_defaults(fn=cmd_tint_hash)
    ti = tnsub.add_parser("inject", help="inject tint into WFT and convert to CFT")
    ti.add_argument("input")
    ti.add_argument("output")
    ti.add_argument("--color", nargs=4, type=float, metavar=("R", "G", "B", "A"),
                    help="tint color as 4 floats (default: 1 1 1 1)")
    ti.set_defaults(fn=cmd_tint_inject)
    tc = tnsub.add_parser("classify", help="classify drawables in a WFT")
    tc.add_argument("file")
    tc.set_defaults(fn=cmd_tint_classify)

    return p


def _pause_if_interactive():
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input("\nPress Enter to exit...")
    except (EOFError, KeyboardInterrupt):
        pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        print("=" * 56)
        print("  GTAIV MOD KIT v%s  -  GTA IV PS3 archive & car mod toolkit" % VERSION)
        print("=" * 56)
        print("Default game dir : %s" % DEFAULT_GAME)
        print("Game dir present : %s" % ("yes" if os.path.isdir(DEFAULT_GAME) else "NOT FOUND"))
        try:
            print("AES key          : %s..." % aes.KEY_HEX[:16])
        except Exception:
            print("AES key          : unavailable")
        print()
        print("This tool is meant to be used from a terminal, e.g.:")
        print("  gtaivkit cars list")
        print("  gtaivkit convert mod.wtd mod.ctd")
        print("  gtaivkit cars install C:\\mymods")
        print("  gtaivkit rgxa pack raw.bin packed.rgxa")
        print("  gtaivkit tint inject model.wft model.cft --color 1 0 0 1")
        print("  gtaivkit rebuild common.rpf extracted")
        print()
        parser.print_help()
        _pause_if_interactive()
        return
    args = parser.parse_args(argv)
    try:
        args.fn(args)
    except (rpfmod.RpfError, imgmod.ImgError, rscmod.RscError) as exc:
        raise SystemExit("error: %s" % exc)


if __name__ == "__main__":
    main()
