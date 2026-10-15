import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gtaivkit import aes
from gtaivkit import img as imgmod
from gtaivkit import manifest as manifestmod
from gtaivkit import rpf as rpfmod
from gtaivkit import rsc as rscmod
from gtaivkit import wft as wftmod
from gtaivkit import wtd as wtdmod

GAME = r"C:\Users\_MO\Desktop\13\PS3_GAME\USRDIR"
PC_IMG = r"C:\Users\_MO\Downloads\Grand Theft Auto IV\pc\models\cdimages\vehicles.img"
RPF_PATHS = [os.path.join(GAME, n) for n in ("common.rpf", "ps3.rpf", "audio.rpf")]
IMG_PATHS = [os.path.join(GAME, "ps3", "models", "cdimages", n)
             for n in ("vehicles.img", "weapons.img", "radar.img")]
EXPECTED_SHA1 = "DEA375EF1E6EF2223A1221C2C575C47BF17EFA5E"

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print("%-4s %s%s" % ("PASS" if cond else "FAIL", name,
                         ("  -- " + detail) if detail and not cond else ""))
    return cond


def rpf_semantic_equal(a, b):
    if a.file_paths != b.file_paths:
        return False, "file list differs"
    for p in a.file_paths:
        ra = a.read(p)
        rb = b.read(p)
        if ra != rb:
            return False, "content differs: %s (%d vs %d)" % (p, len(ra), len(rb))
    return True, "%d files" % len(a.file_paths)


def test_key():
    check("key sha1", aes.KEY_SHA1 == EXPECTED_SHA1, aes.KEY_SHA1)
    check("key hex len", len(aes.KEY_HEX) == 64)
    from Crypto.Cipher import AES
    c = AES.new(aes.KEY, AES.MODE_ECB)
    enc_then_dec = c.decrypt(c.encrypt(b"\x11" * 16))
    roundtrip = aes.crypt16(aes.crypt16(b"\x11" * 16, False), True)
    check("aes roundtrip", enc_then_dec == b"\x11" * 16 and
          roundtrip == b"\x11" * 16)


def test_rpf(path, strict=True):
    name = os.path.basename(path)
    try:
        a = rpfmod.RpfArchive(path)
    except Exception as exc:
        check("rpf parse " + name, False, str(exc))
        return
    check("rpf parse " + name, True, "%d entries" % a.entry_count)
    rebuilt = rpfmod.build(a, {})
    b = rpfmod.RpfArchive.from_bytes(rebuilt, name)
    ok, detail = rpf_semantic_equal(a, b)
    check("rpf semantic " + name, ok, detail)
    if strict:
        check("rpf byte-identical " + name, rebuilt == a.data,
              "sizes %d vs %d" % (len(rebuilt), len(a.data)))


def test_rpf_replace(path):
    name = os.path.basename(path)
    a = rpfmod.RpfArchive(path)
    text_paths = [p for p in a.file_paths if not a.get(p).is_resource
                  and not p.lower().endswith((".rpf", ".img", ".awc", ".mp3"))]
    if not text_paths:
        check("rpf replace (no text files) " + name, True)
        return
    target = text_paths[0]
    original = a.read(target)
    payload = b"// injected by gtaivkit test\r\n" + original
    rebuilt = rpfmod.build(a, {target: payload})
    b = rpfmod.RpfArchive.from_bytes(rebuilt, name)
    check("rpf replace-read " + name, b.read(target) == payload, target)
    others_ok = True
    diff = ""
    for p in a.file_paths:
        if p == target:
            continue
        if a.read(p) != b.read(p):
            others_ok = False
            diff = p
            break
    check("rpf replace leaves others " + name, others_ok, diff)
    again = rpfmod.build(b, {target: original})
    c = rpfmod.RpfArchive.from_bytes(again, name)
    check("rpf replace back " + name, c.read(target) == original, target)


def test_rpf_replace_resource(path):
    name = os.path.basename(path)
    a = rpfmod.RpfArchive(path)
    res = [p for p in a.file_paths if a.get(p).is_resource]
    if not res:
        check("rpf resource replace " + name, True, "no resources")
        return
    target = res[0]
    original = a.read(target)
    rebuilt = rpfmod.build(a, {target: original})
    b = rpfmod.RpfArchive.from_bytes(rebuilt, name)
    check("rpf resource replace " + name, b.read(target) == original, target)
    try:
        rpfmod.build(a, {target: b"not a resource at all"})
        check("rpf resource guard", False, "accepted non-RSC replacement")
    except rpfmod.RpfError:
        check("rpf resource guard", True)


def test_img(path, strict=True):
    name = os.path.basename(path)
    try:
        a = imgmod.ImgArchive(path)
    except Exception as exc:
        check("img parse " + name, False, str(exc))
        return
    rsc = sum(1 for e in a.entries if e.is_resource)
    check("img parse " + name, True,
          "%d entries, %d resource" % (len(a.entries), rsc))
    magic_ok = True
    bad = ""
    for e in a.entries:
        blob = a.stored_bytes(e)
        if e.is_resource and not imgmod.is_resource_blob(blob):
            magic_ok = False
            bad = e.name
            break
        if not e.is_resource and len(blob) != e.size_or_flags:
            magic_ok = False
            bad = "%s (%d != %d)" % (e.name, len(blob), e.size_or_flags)
            break
    check("img entry shapes " + name, magic_ok, bad)
    rebuilt = imgmod.build(a)
    b = imgmod.ImgArchive.from_bytes(rebuilt, name)
    ok = len(a.entries) == len(b.entries)
    detail = "entry count"
    if ok:
        for ea, eb in zip(a.entries, b.entries):
            if ea.name != eb.name or a.stored_bytes(ea) != b.stored_bytes(eb):
                ok = False
                detail = ea.name + " vs " + eb.name
                break
    check("img semantic " + name, ok, detail)
    if strict:
        check("img byte-identical " + name, rebuilt == a.data,
              "sizes %d vs %d" % (len(rebuilt), len(a.data)))


def test_img_replace_and_add(path):
    name = os.path.basename(path)
    a = imgmod.ImgArchive(path)
    target = a.entries[0]
    original = a.stored_bytes(target)
    rebuilt = imgmod.build(a, replacements={target.name: original})
    b = imgmod.ImgArchive.from_bytes(rebuilt, name)
    check("img replace-read " + name, b.stored_bytes(b.get(target.name)) == original,
          target.name)
    extra = b"RSC\x05" + b"\x00" * 60
    if target.is_resource:
        payload = original
        addname = "zztest.rbs"
        rebuilt2 = imgmod.build(a, additions={addname: b"\x00" * 100})
        b2 = imgmod.ImgArchive.from_bytes(rebuilt2, name)
        check("img add " + name, b2.has(addname) and
              b2.stored_bytes(b2.get(addname)) == b"\x00" * 100, addname)
    else:
        check("img add " + name, True, "skipped")
    try:
        imgmod.build(a, replacements={target.name: b"\x01\x02\x03"})
        if target.is_resource:
            check("img resource guard", False, "accepted non-RSC replacement")
        else:
            check("img resource guard", True, "non-resource accepts any bytes")
    except imgmod.ImgError:
        check("img resource guard", True)


def test_cli():
    py = sys.executable
    env = dict(os.environ)
    env["PYTHONPATH"] = HERE

    def run(*args):
        return subprocess.run([py, "-m", "gtaivkit"] + list(args),
                              capture_output=True, text=True, env=env,
                              cwd=HERE)

    r = run("key")
    check("cli key", r.returncode == 0 and aes.KEY_HEX in r.stdout, r.stderr[:200])
    r = run("list", os.path.join(GAME, "common.rpf"))
    check("cli list", r.returncode == 0 and "/data" in r.stdout or "common" in r.stdout,
          r.stderr[:200])
    r = run("cars", "list")
    check("cli cars list", r.returncode == 0 and "admiral" in r.stdout, r.stderr[:300])
    with tempfile.TemporaryDirectory() as td:
        r = run("extract", os.path.join(GAME, "ps3", "models", "cdimages",
                                        "vehicles.img"), "admiral.ctd",
                "-o", td, "--raw")
        ok = r.returncode == 0 and os.path.exists(os.path.join(td, "admiral.ctd"))
        if ok:
            with open(os.path.join(td, "admiral.ctd"), "rb") as fh:
                ok = fh.read(4) in rpfmod.RSC_MAGICS
        check("cli extract", ok, r.stderr[:300] or r.stdout[:300])


def test_manifest():
    with tempfile.TemporaryDirectory() as td:
        img_src = os.path.join(GAME, "ps3", "models", "cdimages", "vehicles.img")
        sub = os.path.join(td, "cdimages")
        os.makedirs(sub)
        shutil.copy(img_src, os.path.join(sub, "vehicles.img"))
        m = manifestmod.build_manifest(td)
        arc = m["archives"].get("cdimages/vehicles.img")
        ok = arc is not None and arc.get("type") == "img3"
        n = len(arc.get("entries", [])) if ok else 0
        check("manifest index", ok and n == 258,
              "type=%s entries=%d" % (arc.get("type") if arc else "?", n))
        rels = [f["path"] for f in m["files"]]
        check("manifest loose files", "cdimages/vehicles.img" in rels, str(rels[:3]))


def test_cli_e2e():
    py = sys.executable
    env = dict(os.environ)
    env["PYTHONPATH"] = HERE

    def run(*args):
        return subprocess.run([py, "-m", "gtaivkit"] + list(args),
                              capture_output=True, text=True, env=env, cwd=HERE)

    veh = os.path.join(GAME, "ps3", "models", "cdimages", "vehicles.img")
    common = os.path.join(GAME, "common.rpf")
    with tempfile.TemporaryDirectory() as td:
        r = run("extract", veh, "admiral.ctd", "-o", td, "--raw")
        ctd = os.path.join(td, "admiral.ctd")
        ok = r.returncode == 0 and os.path.exists(ctd)
        check("cli extract raw ctd", ok, r.stderr[:300])

        veh2 = os.path.join(td, "vehicles.img")
        shutil.copy(veh, veh2)
        out2 = os.path.join(td, "v_same.img")
        r = run("cars", "replace", "admiral", "--ctd", ctd, "--img", veh2,
                "--out", out2, "--no-backup")
        same = ok and open(out2, "rb").read() == open(veh, "rb").read() \
            if r.returncode == 0 else False
        check("cli cars replace same-content", same, r.stderr[:300])

        payload = open(ctd, "rb").read() + b"\x00" * 32
        ctd2 = os.path.join(td, "admiral2.ctd")
        with open(ctd2, "wb") as fh:
            fh.write(payload)
        out3 = os.path.join(td, "v_mod.img")
        r = run("cars", "replace", "admiral", "--ctd", ctd2, "--img", veh2,
                "--out", out3, "--no-backup")
        ok = r.returncode == 0 and os.path.exists(out3)
        if ok:
            b = imgmod.ImgArchive(out3)
            ok = b.stored_bytes(b.get("admiral.ctd")) == payload
        check("cli cars replace modified", ok, r.stderr[:300])

        r = run("cars", "replace", "admiral", "--ctd", ctd, "--img", veh2)
        ok = r.returncode == 0 and os.path.exists(veh2 + ".bak")
        check("cli cars replace backup", ok, r.stderr[:300])

        r = run("cars", "extract", "admiral", "-o", td, "--img", veh)
        ok = (r.returncode == 0
              and os.path.exists(os.path.join(td, "admiral.ctd"))
              and os.path.exists(os.path.join(td, "admiral.cft")))
        check("cli cars extract", ok, r.stderr[:300])

        mods = os.path.join(td, "mods")
        os.makedirs(mods)
        shutil.copy(ctd, os.path.join(mods, "admiral.ctd"))
        shutil.copy(ctd, os.path.join(mods, "notacar.ctd"))
        veh4 = os.path.join(td, "vehicles2.img")
        shutil.copy(veh, veh4)
        r = run("cars", "install", mods, "--img", veh4, "--no-backup")
        ok = r.returncode == 0 and "skipped" in r.stdout
        if ok:
            b = imgmod.ImgArchive(veh4)
            with open(ctd, "rb") as fh:
                want = fh.read()
            ok = (b.stored_bytes(b.get("admiral.ctd")) == want
                  and not b.has("notacar.ctd")
                  and b.stored_bytes(b.get("admiral.cft"))
                  == imgmod.ImgArchive(veh).read("admiral.cft"))
        check("cli cars install", ok, r.stderr[:300] or r.stdout[:300])

        common2 = os.path.join(td, "common.rpf")
        shutil.copy(common, common2)
        r = run("extract", common2, "data/gta.dat", "-o", td)
        gdat = os.path.join(td, "data", "gta.dat")
        ok = r.returncode == 0 and os.path.exists(gdat)
        check("cli extract rpf text", ok, r.stderr[:300])
        if ok:
            with open(gdat, "rb") as fh:
                payload = b"// injected by gtaivkit test\r\n" + fh.read()
            with open(gdat, "wb") as fh:
                fh.write(payload)
            out4 = os.path.join(td, "common2.rpf")
            r = run("inject", common2, gdat, "data/gta.dat", "--no-backup",
                    "--out", out4)
            ok = r.returncode == 0 and os.path.exists(out4)
            if ok:
                c = rpfmod.RpfArchive(out4)
                ok = c.read("data/gta.dat") == payload
            check("cli inject rpf", ok, r.stderr[:300])
            r = run("verify", out4)
            check("cli verify", r.returncode == 0, r.stderr[:300])

        r = run("--game", td, "manifest", "-o", os.path.join(td, "m.json"))
        ok = r.returncode == 0 and os.path.exists(os.path.join(td, "m.json"))
        if ok:
            import json
            with open(os.path.join(td, "m.json"), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            ok = "vehicles.img" in " ".join(data["archives"].keys())
        check("cli manifest", ok, r.stderr[:300] or r.stdout[:300])

        if os.path.exists(PC_IMG):
            pcwtd = os.path.join(td, "admiral_pc.wtd")
            pc = imgmod.ImgArchive(PC_IMG)
            with open(pcwtd, "wb") as fh:
                fh.write(pc.read("admiral.wtd"))
            r = run("inspect", pcwtd)
            check("cli inspect wtd",
                  r.returncode == 0 and "Platform: PC" in r.stdout
                  and "Textures: 4" in r.stdout, r.stderr[:300])
            ctd_out = os.path.join(td, "admiral_new.ctd")
            r = run("convert", pcwtd, ctd_out)
            check("cli convert wtd",
                  r.returncode == 0 and os.path.exists(ctd_out),
                  r.stderr[:300])
            texdir = os.path.join(td, "texout")
            r = run("tex", ctd_out, "-o", texdir)
            n_dds = (len([f for f in os.listdir(texdir) if f.endswith(".dds")])
                     if os.path.isdir(texdir) else 0)
            check("cli tex extract",
                  r.returncode == 0 and n_dds == 4, r.stderr[:300])


def test_rsc_flags():
    check("rsc decode wft flags",
          rscmod.decode_flags(0xD828201A) == (106496, 1310720),
          str(rscmod.decode_flags(0xD828201A)))
    check("rsc decode wtd flags",
          rscmod.decode_flags(0xD80C0010) == (4096, 393216),
          str(rscmod.decode_flags(0xD80C0010)))
    check("rsc decode ps3 cft flags",
          rscmod.decode_flags(0xD0082843) == (548864, 65536),
          str(rscmod.decode_flags(0xD0082843)))
    check("rsc decode ps3 ctd flags",
          rscmod.decode_flags(0xD40F0010) == (4096, 245760),
          str(rscmod.decode_flags(0xD40F0010)))
    ok = True
    detail = ""
    for sys_s, gpu_s in ((4096, 245760), (548864, 65536), (106496, 1310720),
                         (512, 317184)):
        ps = rscmod.pad_size_for_flags(sys_s)
        pg = rscmod.pad_size_for_flags(gpu_s)
        f = rscmod.encode_flags(ps, pg)
        got = rscmod.decode_flags(f)
        if got != (ps, pg):
            ok = False
            detail = "%d/%d -> %s" % (ps, pg, str(got))
    check("rsc flags roundtrip", ok, detail)


def test_wtd_ctd():
    ps3 = imgmod.ImgArchive(os.path.join(GAME, "ps3", "models", "cdimages",
                                         "vehicles.img"))
    rsc = rscmod.RscFile.from_bytes(ps3.read("admiral.ctd"))
    texs = wtdmod.parse(rsc.decompressed, True, rsc.system_size)
    names = [t.name for t in texs]
    formats = [t.format for t in texs]
    sizes = [len(t.pixel_data) if t.pixel_data else 0 for t in texs]
    mips = [t.mip_count for t in texs]
    check("wtd parse real ctd",
          len(texs) == 4 and all(t.name for t in texs)
          and formats == ["DXT5", "DXT1", "DXT5", "DXT1"]
          and sizes == [32768, 21840, 87376, 174760]
          and mips == [1, 6, 7, 8],
          "%d tex %s sizes=%s mips=%s" % (len(texs), formats, sizes, mips))
    dims = {(t.width, t.height) for t in texs}
    check("wtd ctd dims", (256, 128) in dims and (512, 512) in dims,
          str(dims))

    rsc2 = rscmod.RscFile.from_bytes(ps3.read("admiral.cft"))
    check("wft parse real cft", rsc2.is_ps3 and rsc2.type == 117
          and rsc2.system_size + rsc2.gpu_size <= len(rsc2.decompressed),
          "type=%d sys=%d gpu=%d" % (rsc2.type, rsc2.system_size,
                                     rsc2.gpu_size))


def test_ctd_struct_fields():
    ps3 = imgmod.ImgArchive(os.path.join(GAME, "ps3", "models", "cdimages",
                                         "vehicles.img"))
    rsc = rscmod.RscFile.from_bytes(ps3.read("admiral.ctd"))
    dec = rsc.decompressed
    tex_off = wtdmod.ptr_offset(struct.unpack_from(">I", dec, 24)[0])
    tex_count = struct.unpack_from(">H", dec, 30)[0]
    ok = tex_count == 4
    detail = "count=%d" % tex_count
    regs = []
    for i in range(tex_count):
        o = wtdmod.ptr_offset(struct.unpack_from(">I", dec, tex_off + i * 4)[0])
        magic = struct.unpack_from(">I", dec, o)[0]
        size16 = struct.unpack_from("<I", dec, o + 16)[0]
        b20, b21, b22, b23 = dec[o + 20:o + 24]
        f24 = struct.unpack_from(">I", dec, o + 24)[0]
        f32 = struct.unpack_from(">I", dec, o + 32)[0]
        gpu = wtdmod.ptr_offset(struct.unpack_from(">I", dec, o + 48)[0])
        if magic != 0xEC896300 or f24 != 0xAAE4 or f32 != 0x00010000 \
                or b22 != 2 or b23 != 0 or b20 not in (0x86, 0x88) \
                or not (1 <= b21 <= 15):
            ok = False
            detail = "tex%d magic=%08x f24=%08x f32=%08x b=%s" % (
                i, magic, f24, f32, dec[o + 20:o + 24].hex())
        regs.append((rsc.system_size + gpu, size16))
    regs.sort()
    prev = rsc.system_size
    for off, sz in regs:
        if off < prev or off + sz > len(dec):
            ok = False
            detail = "region %d+%d outside [%d,%d]" % (off, sz, prev, len(dec))
            break
        if off > prev and any(b not in (0, 0xCD) for b in dec[prev:off]):
            ok = False
            detail = "gap before %d not padding" % off
            break
        prev = off + sz
    check("game ctd struct fields + relative ptr layout", ok, detail)


def test_dds_export():
    ps3 = imgmod.ImgArchive(os.path.join(GAME, "ps3", "models", "cdimages",
                                         "vehicles.img"))
    rsc = rscmod.RscFile.from_bytes(ps3.read("admiral.ctd"))
    texs = wtdmod.parse(rsc.decompressed, True, rsc.system_size)
    ok = True
    detail = ""
    for t in texs:
        px = t.pixel_data or b""
        d = wtdmod.dds_export(t)
        fourcc = {"DXT1": 0x31545844, "DXT3": 0x33545844}.get(
            t.format[:4], 0x35545844)
        good = (
            d[:4] == b"DDS "
            and struct.unpack_from("<I", d, 4)[0] == 124
            and struct.unpack_from("<I", d, 8)[0] == 0x81007
            and struct.unpack_from("<II", d, 12) == (t.height, t.width)
            and struct.unpack_from("<I", d, 20)[0] == len(px)
            and struct.unpack_from("<I", d, 28)[0] == max(1, t.mip_count)
            and struct.unpack_from("<II", d, 76) == (32, 4)
            and struct.unpack_from("<I", d, 84)[0] == fourcc
            and struct.unpack_from("<I", d, 108)[0] == 4096
            and len(d) == 128 + len(px)
            and d[128:] == px)
        if not good:
            ok = False
            detail = "%s: len=%d flags=%x caps=%d" % (
                t.name, len(d), struct.unpack_from("<I", d, 8)[0],
                struct.unpack_from("<I", d, 108)[0])
            break
    check("dds export header (128 bytes, valid caps)", ok, detail)


def test_convert_wtd_wft():
    if not os.path.exists(PC_IMG):
        check("convert wtd/wft", True, "skipped: no PC game")
        return
    pc = imgmod.ImgArchive(PC_IMG)
    wtd = pc.read("admiral.wtd")
    ctd = wtdmod.convert_to_ctd(wtd)
    rsc = rscmod.RscFile.from_bytes(ctd)
    texs = wtdmod.parse(rsc.decompressed, True, rsc.system_size)
    check("convert wtd->ctd",
          rsc.is_ps3 and rsc.type == 7 and len(texs) == 4
          and rsc.system_size % 4096 == 0,
          "type=%d tex=%d sys=%d" % (rsc.type, len(texs), rsc.system_size))
    pc_texs = wtdmod.parse(rscmod.RscFile.from_bytes(wtd).decompressed, False)
    same_names = [t.name for t in texs] == [t.name for t in pc_texs]
    faithful = all(
        a.pixel_data is not None and a.pixel_data == b.pixel_data
        and a.format == b.format and a.mip_count == b.mip_count
        and a.width == b.width and a.height == b.height
        for a, b in zip(texs, pc_texs))
    check("convert wtd textures faithful", same_names and faithful,
          "names=%s faithful=%s" % (same_names, faithful))
    dec = rsc.decompressed
    tex_off = wtdmod.ptr_offset(struct.unpack_from(">I", dec, 24)[0])
    o = wtdmod.ptr_offset(struct.unpack_from(">I", dec, tex_off)[0])
    struct_ok = (
        struct.unpack_from(">I", dec, o)[0] == 0xEC896300
        and struct.unpack_from("<I", dec, o + 16)[0]
        == len(pc_texs[0].pixel_data)
        and dec[o + 20] == 0x88 and dec[o + 21] == pc_texs[0].mip_count
        and struct.unpack_from(">I", dec, o + 24)[0] == 0xAAE4
        and struct.unpack_from(">I", dec, o + 32)[0] == 0x00010000)
    check("convert ctd struct matches game layout", struct_ok,
          "magic=%08x size=%d b=%s" % (
              struct.unpack_from(">I", dec, o)[0],
              struct.unpack_from("<I", dec, o + 16)[0],
              dec[o + 20:o + 24].hex()))

    wft = wftmod.WftFile.from_bytes(pc.read("admiral.wft"))
    cft = wft.to_ps3()
    rsc2 = rscmod.RscFile.from_bytes(cft)
    check("convert wft->cft",
          rsc2.is_ps3 and rsc2.type == 117
          and rsc2.decompressed == wft.decompressed,
          "type=%d dec=%d" % (rsc2.type, len(rsc2.decompressed)))



def test_rpf3_audio():
    p = os.path.join(GAME, "ps3", "audio", "sfx", "vehicles.rpf")
    if not os.path.exists(p):
        check("rpf3 parse", True, "skipped: no audio rpf")
        return
    arc = rpfmod.RpfArchive(p)
    files = arc.list_files()
    ok = arc.kind == "RPF3" and len(files) == 6 \
        and "VEHICLES/WHEEL_LOOPS" in files and "VEHICLES/HORNS" in files
    check("rpf3 parse + hash names", ok,
          "kind=%s files=%d" % (arc.kind, len(files)))
    read_ok = True
    detail = ""
    for f in files:
        e = arc.get(f)
        blob = arc.read(f)
        if len(blob) != e.size:
            read_ok = False
            detail = "%s: %d != %d" % (f, len(blob), e.size)
            break
    check("rpf3 read all entries", read_ok, detail)
    out = rpfmod.build(arc, {})
    check("rpf3 rebuild byte-identical", out == arc.data,
          "%d vs %d" % (len(out), len(arc.data)))


def test_img3_plaintext():
    p = os.path.join(GAME, "common", "data", "cdimages", "navgen_script.img")
    if not os.path.exists(p):
        check("img3 plaintext parse", True, "skipped: no navgen_script.img")
        return
    arc = imgmod.ImgArchive(p)
    names = arc.list_names()
    check("img3 plaintext parse",
          arc.encrypted is False and names == ["navgen_main.sco"],
          "enc=%s names=%s" % (arc.encrypted, names))
    blob = arc.read("navgen_main.sco")
    check("img3 plaintext read",
          len(blob) == 165888 and blob[:3] == b"SCR",
          "len=%d head=%r" % (len(blob), blob[:4]))
    out = imgmod.build(arc, {})
    check("img3 plaintext rebuild byte-identical", out == arc.data,
          "%d vs %d" % (len(out), len(arc.data)))


def test_cli_new_formats():
    py = sys.executable
    env = dict(os.environ)
    env["PYTHONPATH"] = HERE

    def run(*args):
        return subprocess.run([py, "-m", "gtaivkit"] + list(args),
                              capture_output=True, text=True, env=env, cwd=HERE)

    rpf3 = os.path.join(GAME, "ps3", "audio", "sfx", "vehicles.rpf")
    if os.path.exists(rpf3):
        r = run("list", rpf3)
        check("cli list rpf3",
              r.returncode == 0 and "WHEEL_LOOPS" in r.stdout,
              r.stderr[:200] or r.stdout[:200])
    img3 = os.path.join(GAME, "common", "data", "cdimages", "navgen_script.img")
    if os.path.exists(img3):
        r = run("list", img3)
        check("cli list img3 plaintext",
              r.returncode == 0 and "navgen_main.sco" in r.stdout,
              r.stderr[:200] or r.stdout[:200])
        with tempfile.TemporaryDirectory() as td:
            r1 = run("extract", img3, "-o", td)
            r2 = run("rebuild", img3, td)
            check("cli rebuild extract folder (no changes)",
                  r1.returncode == 0 and r2.returncode == 0
                  and "no changes" in r2.stdout,
                  (r2.stderr or r2.stdout)[:200])


def test_rebuild():
    from gtaivkit import rebuild as rebuildmod

    def dump(arc, td, paths):
        for p in paths:
            blob = arc.read(p)
            tgt = os.path.join(td, p.replace("/", os.sep))
            os.makedirs(os.path.dirname(tgt) or ".", exist_ok=True)
            with open(tgt, "wb") as fh:
                fh.write(blob)

    rpf3 = os.path.join(GAME, "ps3", "audio", "sfx", "script_ambient.rpf")
    if os.path.exists(rpf3):
        with tempfile.TemporaryDirectory() as td:
            arc = rpfmod.RpfArchive(rpf3)
            paths = arc.list_files()
            dump(arc, td, paths)
            out = os.path.join(td, "_out.rpf")
            st = rebuildmod.rebuild(rpf3, td, out_path=out, backup=False)
            check("rebuild rpf3 unchanged skips write",
                  st["written"] is False
                  and st["unchanged"] == st["total"] == len(paths),
                  str(st))
            victim = paths[0]
            with open(os.path.join(td, victim.replace("/", os.sep)),
                      "ab") as fh:
                fh.write(b"XX")
            st = rebuildmod.rebuild(rpf3, td, out_path=out, backup=False)
            a2 = rpfmod.RpfArchive(out)
            others = all(a2.read(f) == arc.read(f)
                         for f in paths if f != victim)
            check("rebuild rpf3 write with change",
                  st["written"] and st["changed"] == [victim]
                  and a2.read(victim).endswith(b"XX") and others,
                  str(st.get("changed")))
            with open(os.path.join(td, "extra.bin"), "wb") as fh:
                fh.write(b"zz")
            err = ""
            try:
                rebuildmod.rebuild(rpf3, td, out_path=out, backup=False)
            except ValueError as exc:
                err = str(exc)
            check("rebuild rejects unknown files", "extra.bin" in err,
                  err[:120])
    else:
        check("rebuild rpf3", True, "skipped: no script_ambient.rpf")

    img3 = os.path.join(GAME, "common", "data", "cdimages",
                        "navgen_script.img")
    if os.path.exists(img3):
        with tempfile.TemporaryDirectory() as td:
            arc = imgmod.ImgArchive(img3)
            names = [e.name for e in arc.entries]
            dump(arc, td, names)
            out = os.path.join(td, "_out.img")
            st = rebuildmod.rebuild(img3, td, out_path=out, backup=False)
            check("rebuild img3 unchanged skips write",
                  st["written"] is False, str(st))
            disk = os.path.join(td, names[0])
            with open(disk, "r+b") as fh:
                fh.seek(100)
                fh.write(b"\x99\x88")
            st = rebuildmod.rebuild(img3, td, out_path=out, backup=False)
            a2 = imgmod.ImgArchive(out)
            check("rebuild img3 write with change",
                  st["written"] and st["changed"] == names
                  and a2.read(names[0])[100:102] == b"\x99\x88",
                  str(st.get("changed")))
    else:
        check("rebuild img3", True, "skipped: no navgen_script.img")

    pv = os.path.join(GAME, "ps3", "models", "cdimages", "vehicles.img")
    if os.path.exists(pv):
        with tempfile.TemporaryDirectory() as td:
            src = imgmod.ImgArchive(pv)
            blob = src.read("blista.ctd")
            with open(os.path.join(td, "admiral.ctd"), "wb") as fh:
                fh.write(blob)
            out = os.path.join(td, "_vehicles.img")
            st = rebuildmod.rebuild(pv, td, out_path=out, backup=False)
            a2 = imgmod.ImgArchive(out)
            same = a2.read("admiral.ctd") == blob
            diff = sum(1 for e in src.entries if e.name != "admiral.ctd"
                       and a2.read(e.name) != src.read(e.name))
            check("rebuild img subset keeps other entries",
                  st["written"] and st["changed"] == ["admiral.ctd"]
                  and same and diff == 0
                  and [e.name for e in a2.entries]
                  == [e.name for e in src.entries],
                  "changed=%s diff=%d" % (st.get("changed"), diff))
    else:
        check("rebuild img subset", True, "skipped: no vehicles.img")


def main():
    print("== key ==")
    test_key()
    print("== rpf ==")
    for p in RPF_PATHS:
        test_rpf(p, strict=True)
    print("== rpf replace ==")
    for p in RPF_PATHS:
        test_rpf_replace(p)
        test_rpf_replace_resource(p)
    print("== img ==")
    for p in IMG_PATHS:
        test_img(p, strict=True)
    print("== img replace/add ==")
    for p in IMG_PATHS:
        test_img_replace_and_add(p)
    print("== manifest ==")
    test_manifest()
    print("== cli ==")
    test_cli()
    print("== cli e2e ==")
    test_cli_e2e()
    print("== rsc ==")
    test_rsc_flags()
    print("== wtd/wft ==")
    test_wtd_ctd()
    test_ctd_struct_fields()
    test_dds_export()
    print("== convert ==")
    test_convert_wtd_wft()
    print("== rpf3/img3 formats ==")
    test_rpf3_audio()
    test_img3_plaintext()
    test_cli_new_formats()
    print("== rebuild from folder ==")
    test_rebuild()
    bad = [r for r in results if not r[1]]
    print("\n%d/%d passed" % (len(results) - len(bad), len(results)))
    if bad:
        for name, _, detail in bad:
            print("  FAILED: %s -- %s" % (name, detail))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
