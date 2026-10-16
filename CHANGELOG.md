# Changelog

## v2.0.0 (2026-10-16)

### New Features
- **RGXA resource pack/unpack** — full support for the RageX `RGXA` container format (XOR key16 + raw deflate). New module `gtaivkit/rgxa.py` with `pack_rgxa`, `unpack_rgxa`, and `is_rgxa` helpers. CLI: `gtaivkit rgxa pack/unpack`.
- **Shader tint injection** — inject tint parameters into WFT meshes before PS3 conversion. Renames known shader samplers (`texturesampler` → `ragex_tint`, `dirtsampler`/`specsampler` → `ragex_tint_zero`) and patches tint floats. CLI: `gtaivkit tint inject`.
- **Drawable classification** — classify WFT drawables into glass / door / window / body sets using the exact part-name rules from the RageX converter. CLI: `gtaivkit tint classify`.
- **Shader hash calculator** — compute the FNV-like shader name hash used by the converter. CLI: `gtaivkit tint hash`.

### Improved
- Version bumped to **2.0.0**.
- CLI banner shows version and the new tint/rgxa commands.
- `wft.py` now supports `inject_tint()` for in-place tint application before PS3 conversion.
- `wtd.py` refactored (no functional changes; cleaner imports).

### Under the Hood
- New modules: `gtaivkit/rgxa.py`, `gtaivkit/tint.py`.
- `__init__.py` exports the new modules and bumps `__version__` to `2.0.0`.
- All existing features (RPF/IMG round-trips, WTD↔CTD, DDS export, convert-archive) remain unchanged.

---

## v1.0.0 (initial)

- RPF2/RPF3/IMG3 archive read/write with AES-256-ECB ×16 header encryption.
- WTD ↔ CTD conversion (game-faithful PS3 struct).
- DDS texture export.
- `vehicles.img` batch conversion from PC sources (`--textures-only` safe mode).
- Arabic RTL GUI + full CLI.
- Manifest generator for the whole game directory.
