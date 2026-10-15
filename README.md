# GTAIV Mod Kit

Open-source toolkit for inspecting, extracting and modding **GTA IV (PS3)**
archives and vehicle files — with a full CLI and an Arabic (RTL) GUI.

> Not affiliated with Rockstar Games. Requires your own game files.
> Released under the MIT License — see [LICENSE](LICENSE).

## Features

- **Archive support**
  - `RPF2` / `RPF3` (encrypted + decrypted), including PS3 audio `.rpf` with
    hashed file names (`hashes.ini` lookup)
  - `IMG3` (`0xA94E2A52`) — encrypted and plain-text variants
  - All builds are **byte-identical** round-trips (read → write → identical file)
- **Vehicle workflow** — list / extract / replace / install cars
  (`.ctd` texture dict + `.cft` mesh) with automatic `.bak` backups
- **WTD/CTD tools**
  - Game-faithful PS3 `CTD` builder (struct matches retail files:
    magic `0xEC896300`, format bytes `0x86/0x88`, field `0xAAE4`,
    GPU pointers relative to `system_size`)
  - PC `WTD` → PS3 `CTD` and `CTD` → `WTD` conversion, preserving formats,
    full mip chains and pixel data
  - **DDS export** with a correct 128-byte header (`DDS `, flags `0x81007`,
    caps, fourcc) — textures open in any DDS viewer
- **WFT/CFT** mesh conversion PC ↔ PS3
- **Rebuild archives from a folder** — extract everything, edit files with any
  external tool, then repack the whole archive in one step
  (`rebuild` command / «إعادة بناء من مجلد» button), with `.bak` restore
- **Manifest / verify** — integrity checks for whole directories

## Requirements

- Python 3.10+ (developed on 3.14)
- `pycryptodome` (AES) — `pip install pycryptodome`
- GUI only: `PySide6` — `pip install PySide6`
- Tests: `python tests.py` (uses the real game files; set `GAME` / `PC_IMG`
  constants at the top of `tests.py`)

## CLI quick start

```bat
python -m gtaivkit list <archive>
python -m gtaivkit extract <archive> [inner paths...] -o outdir
python -m gtaivkit inject <archive> <inner path> <file>
python -m gtaivkit rebuild <archive> <folder> [-o out] [--add] [--no-backup]
python -m gtaivkit cars list <vehicles.img>
python -m gtaivkit cars extract <vehicles.img> <car name> -o cars
python -m gtaivkit cars replace <vehicles.img> <car name> <new .ctd/.cft>
python -m gtaivkit inspect <wtd/cft/ctd file>
python -m gtaivkit tex <wtd/ctd file> -o textures
python -m gtaivkit convert <file.wtd> -o file.ctd
python -m gtaivkit verify / manifest / key
```

Run `python -m gtaivkit --help` or `python -m gtaivkit <cmd> --help` for all
options. A `--game <USRDIR>` option points the tool at a game folder.

## GUI

```bat
python run_gui.py
```

or build standalone executables:

```bat
python -m PyInstaller --onefile --console --name gtaivkit ^
  --icon icon.ico --version-file version_info.txt ^
  --add-data "gtaivkit\hashes.ini;gtaivkit" gtaivkit_exe.py

python -m PyInstaller --onefile --windowed --name GTAIVModKit ^
  --icon icon.ico --version-file version_info.txt ^
  --add-data "gtaivkit\hashes.ini;gtaivkit" run_gui.py
```

Pages: Files (browse/extract/inject/rebuild) · Cars · Textures (DDS) ·
Convert · Manifest.

## Project layout

```
gtaivkit/          the library + CLI (python -m gtaivkit)
  aes.py           PS3 AES-256 key schedule (crypt16)
  rpf.py           RPF2/RPF3 archives
  img.py           IMG3 archives
  rsc.py           RSC resource headers (decompress/encode, PS3/PC)
  wtd.py           texture dicts, DDS export, PS3 CTD build/parse
  wft.py           mesh dicts PC/PS3
  cars.py          vehicle replace/extract/install
  rebuild.py       rebuild an archive from an extracted folder
  manifest.py      directory manifests / verify
  hashnames.py     RPF3 hash-name resolution
  cli.py           argparse CLI
  gui.py           PySide6 Arabic RTL GUI
  hashes.ini       file-name hash table for RPF3
run_gui.py         GUI entry point
gtaivkit_exe.py    CLI entry point (for PyInstaller)
tests.py           test suite (94 checks)
```

## ملاحظة بالعربية

هذا المشروع مفتوح المصدر بالكامل (رخصة MIT): تستطيع نسخه وتعديله ونشره
بحرية. للأوامر:

```bat
python -m gtaivkit --help
python run_gui.py
python tests.py
```

يقرأ الملفات الأصلية للعبة فقط ولا يعدّلها إلا بعد طلب صريح (وتُنسخ نسخة
احتياطية `.bak` قبل أي إعادة بناء).
