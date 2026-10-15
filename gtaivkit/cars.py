import os

from . import img as imgmod

VEHICLES_IMG = "ps3/models/cdimages/vehicles.img"

PARTS = ("ctd", "cft")


def default_img(game_dir):
    return os.path.join(game_dir, VEHICLES_IMG.replace("/", os.sep))


def list_cars(img_path):
    arc = imgmod.ImgArchive(img_path)
    cars = {}
    for e in arc.entries:
        stem, _, ext = e.name.lower().rpartition(".")
        if not stem:
            continue
        cars.setdefault(stem, {})[ext] = e.stored_size
    return cars


def extract_car(img_path, model, out_dir):
    model = model.lower()
    arc = imgmod.ImgArchive(img_path)
    written = []
    for ext in PARTS:
        name = "%s.%s" % (model, ext)
        if not arc.has(name):
            continue
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(arc.read(name))
        written.append(name)
    if not written:
        raise imgmod.ImgError(
            "no .ctd/.cft for model %s in %s (use 'cars list')" % (model, img_path))
    return written


def install_folder(img_path, folder, out_path=None, backup=True):
    arc = imgmod.ImgArchive(img_path)
    known = set()
    for e in arc.entries:
        stem, _, ext = e.name.lower().rpartition(".")
        if stem and ext in PARTS:
            known.add(stem + "." + ext)
    replacements = {}
    skipped = []
    for fn in sorted(os.listdir(folder)):
        low = fn.lower()
        if not low.endswith("." + PARTS[0]) and not low.endswith("." + PARTS[1]):
            continue
        stem, _, ext = low.rpartition(".")
        name = stem + "." + ext
        if name not in known:
            skipped.append(fn)
            continue
        with open(os.path.join(folder, fn), "rb") as fh:
            replacements[name] = fh.read()
    if not replacements:
        raise imgmod.ImgError(
            "no matching .ctd/.cft files in %s (models must already exist; "
            "use 'cars list')" % folder)
    if out_path is None:
        out_path = img_path
        if backup:
            bak = img_path + ".bak"
            if not os.path.exists(bak):
                with open(img_path, "rb") as src, open(bak, "wb") as dst:
                    dst.write(src.read())
    out = imgmod.replace_entries(img_path, replacements=replacements,
                                 out_path=out_path)
    return out, sorted(replacements), skipped


def replace_car(img_path, model, ctd_path=None, cft_path=None, out_path=None,
                backup=True):
    model = model.lower()
    arc = imgmod.ImgArchive(img_path)
    replacements = {}
    for ext, src in (("ctd", ctd_path), ("cft", cft_path)):
        if src is None:
            continue
        name = "%s.%s" % (model, ext)
        if not arc.has(name):
            raise imgmod.ImgError(
                "no entry %s in %s (known models: use 'cars list')" %
                (name, img_path))
        with open(src, "rb") as fh:
            replacements[name] = fh.read()
    if not replacements:
        raise imgmod.ImgError("nothing to replace: pass --ctd and/or --cft")
    if out_path is None:
        out_path = img_path
        if backup:
            bak = img_path + ".bak"
            if not os.path.exists(bak):
                with open(img_path, "rb") as src, open(bak, "wb") as dst:
                    dst.write(src.read())
    return imgmod.replace_entries(img_path, replacements=replacements,
                                  out_path=out_path)
