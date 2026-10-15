# GTAIV Mod Kit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

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

## Roadmap — what's missing / help wanted

Concrete tasks for contributors who want to take this to professional grade.
Anything here is a great first issue:

1. **Mesh (WFT/CFT) payload conversion** — `WftFile.to_ps3()`/`to_pc()` only
   re-tag the 12-byte RSC header and re-compress the payload *unchanged*.
   Full PC↔PS3 conversion needs system/GPU segment layout, pointer tagging
   and buffer-format handling, then a load test on console or RPCS3.
   (Texture dicts *are* fully rebuilt and structurally verified against
   retail files — use `wtd.build_ps3` as the reference pattern.)
2. **Game-independent test fixtures** — `tests.py` reads your own game files
   (`GAME`, `PC_IMG` constants). Generate tiny synthetic RPF/IMG/RSC fixtures
   so the suite can run without any game data.
3. **CI** — GitHub Actions: lint + tests on Windows/Linux/macOS. Blocked on
   task 2; once fixtures exist, add `.github/workflows/ci.yml`.
4. **Packaging** — add `pyproject.toml` with `console_scripts`
   (`gtaivkit = gtaivkit.cli:main`), version single-sourced, installable via
   `pipx install .`.
5. **Release automation** — CI builds the PyInstaller executables
   (`gtaivkit.exe` console, `GTAIVModKit.exe` windowed) and attaches them to
   tagged releases with SHA-256 checksums.
6. **More game formats** — AWC/RF64 audio containers, `.dat`/`.ide` meta
   editors, particles, animations, collisions, and a RPF3 hash-collision
   checker for `hashes.ini`.
7. **GUI** — English localization (all strings are currently Arabic),
   drag & drop, cancellable long operations, dark theme.
8. **Code quality** — type hints + `mypy`, `ruff` formatting, docstrings on
   public APIs, and replacing magic numbers with named constants
   (the RSC/CTD field tables are documented in issues).
9. **Console verification matrix** — document which cars/archives were tested
   on real hardware vs RPCS3, with a smoke-test checklist for releases.
10. **Docs** — architecture overview and format notes (RPF entry layout,
    IMG3 header, RSC flag encoding, PS3 CTD struct table) in `docs/`.

### Known limitations

- Mesh conversion is experimental (task 1); textures are production-ready.
- `.dat`/`.ide` text data files are copied verbatim, not parsed.
- Windows is the primary target; the library itself is cross-platform but
  only the CLI has been exercised outside Windows.

## Contributing

1. Fork and create a feature branch (`git checkout -b feature/my-thing`).
2. Keep the golden rules:
   - **Byte-identical round-trips** — read → write must reproduce the
     original archive when nothing changed.
   - **Magic guards** — never let a resource payload land in a plain
     archive or vice versa.
   - **Backups** — any in-place write gets a `.bak` first; writes are atomic
     (`.tmp` + `os.replace`).
3. Run `python tests.py` (all green) before opening a PR.
4. Open a PR with a short description of the format/behaviour you touched.

Issues labelled *help wanted* in the roadmap above are good starting points.

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
