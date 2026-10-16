# GTAIV Converter — Full Reverse-Engineering Project

> **Open-source reverse engineering** of `GTAIV_Converter_by_TEAM_RageX.exe`
> (PE32+ x64, MSVC 14.44, ImageBase `0x140000000`, v1.3.2).
>
> Every key, format, algorithm and processing step documented below was
> **verified programmatically** (decryption + inflate on the actual embedded
> resources).

---

## Table of Contents

- [Overview](#overview)
- [What This Project Contains](#what-this-project-contains)
- [Quick Start](#quick-start)
- [Crypto Keys](#crypto-keys)
- [RGXA Container Format](#rgxa-container-format)
- [vehicles.img Format](#vehiclesimg-format)
- [Embedded Converters](#embedded-converters)
- [WFT Processing Pipeline](#wft-processing-pipeline)
- [Tint Injection Algorithm](#tint-injection-algorithm)
- [Part Classification Rules](#part-classification-rules)
- [WTD / CTD Formats](#wtd--ctd-formats)
- [Shader Hash (FNV-like)](#shader-hash-fnv-like)
- [Function RVA Table](#function-rva-table)
- [Embedded Resource Manifest](#embedded-resource-manifest)
- [How the Decompilation Works](#how-the-decompilation-works)
- [How to Rebuild / Extend](#how-to-rebuild--extend)
- [Python Pseudocode](#python-pseudocode)
- [License](#license)

---

## Overview

This project documents the complete internal workings of a GTA IV vehicle
converter tool. The original executable embeds three Rockstar converter
binaries, a texture converter, shader parameter files, and a screenshot —
all packed with XOR + raw-deflate (RGXA container).

The research produced:

1. **Full decryption keys** (XOR-16 for embedded resources, AES-256 for `vehicles.img`)
2. **Complete format specifications** (RGXA, vehicles.img, WTD/RSC5, CTD)
3. **Algorithm documentation** (tint injection, part classification, shader hashing)
4. **Python reimplementation** of all critical algorithms
5. **Full decompilation** of the PE (48,088 lines of pseudo-C, 265 functions)

---

## What This Project Contains

| File | Size | Purpose |
|------|------|---------|
| `EXTRACTED_FINDINGS.md` | 21 KB | Complete Arabic+English findings document (all keys, formats, algorithms) |
| `REWRITE_PLAN.md` | 14 KB | Arabic rewrite plan with architecture proposals |
| `decompile.py` | 20 KB | Capstone-based decompiler (produces `code_map.json`) |
| `full_decompile_all.py` | 22 KB | Full decompiler (produces `GTAIV_Converter_FULL_DECOMPILE.c`) |
| `decomp_map.py` | 8 KB | Function/string/IAT mapping tool |
| `find_key_funcs.py` | 1 KB | Locates key functions by string references |
| `code_map.json` | 72 KB | Function/string/IAT mapping output |
| `DECOMPRESSED_CODE.c` | 3 MB | Full pseudo-C decompilation (48,088 lines, 265 functions) |
| `unpacked/` | ~2.5 MB | Extracted embedded resources (converters, shaders, screenshot) |

---

## Quick Start

### Prerequisites

```bash
pip install pefile capstone
```

### Extract embedded resources

```bash
python -c "
from unpack_rgxa import unpack_all
unpack_all('GTAIV_Converter_by_TEAM_RageX.exe', 'unpacked/')
"
```

### Run the decompiler

```bash
# Produce code_map.json
python decompile.py

# Produce full decompilation (48K lines)
python full_decompile_all.py

# Locate key functions
python find_key_funcs.py
```

### Read the findings

Open `EXTRACTED_FINDINGS.md` — it contains every key, format, and algorithm
with Python code ready to use.

---

## Crypto Keys

### XOR Key (Embedded Resources)

```
Key:    9e3bd74261ca158f2db074e9531ca6f8
RVA:    0x78788 → VA 0x140078788
```

**Algorithm:**
```python
def xor_decrypt(data, key=bytes.fromhex('9e3bd74261ca158f2db074e9531ca6f8')):
    out = bytearray(data)
    for i in range(len(out)):
        mixed = ((i * 0x1F + 7) & 0xFF) ^ key[i & 0xF]
        out[i] ^= mixed
    return bytes(out)
```

### AES-256 Key (vehicles.img only)

```
Key:    1ab56fed7ec3ff01227b691533975dce47d769653ff775426a96cd6d5307565d
RVA:    0x78540 → VA 0x140078540
Mode:   ECB (no IV), via bcrypt (BCryptGenerateSymmetricKey + ChainingModeECB)
Rounds: 16 (same block decrypted 16 times)
```

**Important:** Embedded resources use **XOR only** — AES is for `vehicles.img` on disk.

---

## RGXA Container Format

Every embedded resource (RT_RCDATA IDs 101–108) is packed with XOR + raw-deflate.

```
Structure after XOR decryption:
  +0x00  u32  magic    = 0x41584752  ("RGXA" LE)
  +0x04  u32  raw_size = decompressed size
  +0x08  ...  raw deflate data (no zlib header)
```

**Full pipeline:**
```python
import zlib

def rgxa_unpack(resource_bytes):
    dec = xor_decrypt(resource_bytes)
    assert dec[0:4] == b'RGXA'
    raw_size = int.from_bytes(dec[4:8], 'little')
    plain = zlib.decompress(dec[8:], -15)  # raw deflate
    assert len(plain) == raw_size
    return plain

def rgxa_pack(plain):
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    compressed = comp.compress(plain) + comp.flush()
    header = b'RGXA' + len(plain).to_bytes(4, 'little')
    return xor_encrypt(header + compressed)
```

**Verified:** All 7 resources (101–108) decrypt + inflate to exact `unpacked/` sizes.

---

## vehicles.img Format

### Header (20 bytes)

```
  +0x00  u32  magic       = 0xA94E2A52  (after AES decrypt)
  +0x04  u32  version     = 3
  +0x08  u32  entry_count (2 .. 100002)
  +0x0C  u32  data_size   (≤ 0x1000000 = 16MB)
  +0x10  u16  entry_size  = 16
  +0x12  u16  (reserved)
```

### Entry Table (48 bytes per entry on disk)

```c
struct VehicleEntry {          // 48 (0x30) bytes
    u32  field_00;             // +0x00
    u32  field_04;             // +0x04
    u32  field_08;             // +0x08
    u16  field_0C;             // +0x0C
    u16  field_0E;             // +0x0E
    char name[32];             // +0x10  (NUL-padded filename)
};
```

### Decryption

```python
from Crypto.Cipher import AES

AES_KEY = bytes.fromhex('1ab56fed7ec3ff01227b691533975dce47d769653ff775426a96cd6d5307565d')

def decrypt_vehicles_header(data):
    header = bytearray(data[:16])
    cipher = AES.new(AES_KEY, AES.MODE_ECB)
    for _ in range(16):  # 16 rounds on same block
        header[:16] = cipher.decrypt(bytes(header[:16]))
    return bytes(header) + data[16:]
```

---

## Embedded Converters

| Resource ID | File | Output | Platform |
|-------------|------|--------|----------|
| 101 | `ivCellConverter.exe` | `.cft` / `.ctd` | PS3 (Cell) |
| 102 | `ivXenonConverter.exe` | `.xft` | Xbox 360 |
| 103 | `ivXtdConverter.exe` | `.xtd` | Generic |
| 104 | `ragex_texconv.exe` | `.dds` textures | DirectXTex |
| 105 | `shader_params_gcm.txt` | — | PS3 shader params |
| 106 | `shader_params_xenon.txt` | — | Xbox shader params |
| 107 | `ui_screenshot.png` | — | UI screenshot |

**Converter selection** (sub_d640 @ 0x14000d640):
- `ebx == 1` → `ivCellConverter.exe`
- `edi == 0` → `ivXenonConverter.exe`
- else → `ivXtdConverter.exe`

---

## WFT Processing Pipeline

```
1. Read .wft file
2. Call sub_21630 (main processor):
   ├── Parse WFT structure (drawables, shaders, vertex/index buffers)
   ├── Classify parts by name:
   │   ├── sub_1e790: glass parts (windscreen, window_*)
   │   ├── sub_1eb40: misc_/door_/boot
   │   ├── sub_1ecd0: contains "window"
   │   └── sub_1ee90: contains "glass" or "window"
   ├── Patch shaders (color tinting):
   │   ├── sub_20340: inject ragex_tint / ragex_tint_zero
   │   │   ├── hash("texturesampler") → rename to "ragex_tint"
   │   │   ├── hash("dirtsampler")    → rename to "ragex_tint_zero"
   │   │   └── hash("specsampler")    → rename to "ragex_tint_zero"
   │   └── sub_21630: handle gta_vehicle_vehglass
   ├── Patch parts:
   │   ├── Inject tint values (16 bytes RGBA float) into matching shaders
   │   ├── Add gta_vehicle_vehglass shader + .sps source
   │   └── Rebuild index buffers if needed (sub_1dec0: ".tinttmp")
   └── Rebuild layout
3. Write patched .wft
```

---

## Tint Injection Algorithm

### Shader Name Hash (FNV-like)

```python
def fnv_shader_hash(name):
    h = 0
    for c in name.lower():
        h = (ord(c) + h) * 0x401
        h &= 0xFFFFFFFF
        h ^= h >> 6
        h = h * 9
        h &= 0xFFFFFFFF
        h ^= h >> 11
        h = h * 0x8001
        h &= 0xFFFFFFFF
    return h
```

### Replacement Rules

| Input Shader | Hash | Replacement |
|--------------|------|-------------|
| `texturesampler` | `0x24C1C13C` | `ragex_tint` |
| `dirtsampler` | — | `ragex_tint_zero` |
| `specsampler` | — | `ragex_tint_zero` |
| `gta_vehicle_vehglass` | — | New shader appended |

### Pointer Encoding

```
new_ptr = (aligned_offset | 0x50000000)
  - High nibble: 5 (tag)
  - Low 28 bits: offset
```

---

## Part Classification Rules

| Function | Rule | Result |
|----------|------|--------|
| `sub_1e790` | Exact match: `windscreen`, `windscreen_r`, `window_lf/rf/lr/rr/lm/rm` | Glass |
| `sub_1eb40` | Prefix: `misc_`, `door_` or exact: `boot` | Door/Misc |
| `sub_1ecd0` | Substring: `window` | Window |
| `sub_1ee90` | Substring: `glass` or `window` | Glass |

**Usage:**
- `bodyshell` / `chassis` / `boot` → stay in file, treated as fixed parts
- `door_*` → treated specially (can be detached/replaced)
- `misc_*` → additional checks
- Glass parts (`windscreen`, `window_*`) → receive tint injection

---

## WTD / CTD Formats

### WTD (RSC5)

```
Magic:   "RSC5" (0x52534305)
Version: 8
Header at +8:
  raw = u32_le(data[8:12])
  field_a = (raw >> 11) & 0xF        # alignment bits buffer1
  size_a  = (raw & 0x7FF)            # buffer1 size (units)
  field_b = (raw >> 26) & 0xF        # alignment bits buffer2
  size_b  = (raw >> 15) & 0x7FF      # buffer2 size
  actual_size_a = size_a << (field_a + 8)
  actual_size_b = size_b << (field_b + 8)
```

**Validation:**
```
actual_size_a - 0x20 ≤ 0x7FFFFE0
actual_size_b > actual_size_a
actual_size_b ≤ 0x20000000
```

### CTD

```
Version: 9
Min size: 0x40
Max size: 0x7FFFFC0 + 0x40
Header: 0x20 bytes (via sub_13280)
```

---

## Shader Hash (FNV-like)

```python
def fnv_hash(name):
    h = 0
    for c in name.encode('ascii'):
        h = ((c + h) * 0x401) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h * 9) & 0xFFFFFFFF
    h ^= h >> 11
    h = (h * 0x8001) & 0xFFFFFFFF
    return h

# Test:
assert fnv_hash('texturesampler') == 0x24C1C13C
```

---

## Function RVA Table

| RVA | VA | Size | Function |
|-----|-----|------|----------|
| `0x6510` | `0x140006510` | — | WinMain |
| `0x8080` | `0x140008080` | 8512 | WFT pipeline |
| `0xbc90` | `0x14000bc90` | — | CreateProcessW launcher |
| `0xcc00` | `0x14000cc00` | — | Converter output check |
| `0xd1c0` | `0x14000d1c0` | — | Temp workspace manager |
| `0xd640` | `0x14000d640` | — | Converter selector |
| `0xfdd0` | `0x14000fdd0` | — | AES-256-ECB init (bcrypt) |
| `0x101b0` | `0x1400101b0` | — | vehicles.img header decrypt |
| `0x1242a` | `0x14001242a` | — | vehicles.img encrypt (write) |
| `0x1dec0` | `0x14001dec0` | 1888 | Index buffer rebuild (".tinttmp") |
| `0x1e790` | `0x14001e790` | 928 | Glass part classifier |
| `0x1eb40` | `0x14001eb40` | 400 | misc_/door_/boot classifier |
| `0x1ecd0` | `0x14001ecd0` | 448 | Window substring check |
| `0x1ee90` | `0x14001ee90` | 528 | Glass/window substring check |
| `0x20340` | `0x140020340` | 3024 | Tint injection (ragex_tint) |
| `0x21630` | `0x140021630` | 13696 | Main WFT processor |
| `0x33f90` | `0x140033f90` | 1312 | RGXA resource unpacker |
| `0x34900` | `0x140034900` | 496 | WTD processor (RSC5) |
| `0x387b0` | `0x1400387b0` | 2272 | CTD processor |

---

## Embedded Resource Manifest

| ID | File | Purpose |
|----|------|---------|
| 101 | `ivCellConverter.exe` | WFT → CFT/CTD (PS3) |
| 102 | `ivXenonConverter.exe` | WFT → XFT (Xbox 360) |
| 103 | `ivXtdConverter.exe` | WFT → XTD |
| 104 | `ragex_texconv.exe` | Texture conversion (DXT) |
| 105 | `shader_params_gcm.txt` | PS3 shader parameters |
| 106 | `shader_params_xenon.txt` | Xbox shader parameters |
| 107 | `ui_screenshot.png` | UI screenshot |
| 108 | *(reserved)* | — |

---

## How the Decompilation Works

### Tools Used

| Tool | Purpose |
|------|---------|
| `pefile` | PE parsing (sections, imports, resources) |
| `capstone` | x86-64 disassembly engine |
| `re` | String extraction (ASCII + UTF-16) |
| `json` | Function/string/IAT mapping output |

### Pipeline

```
1. Parse PE headers (pefile)
   ├── ImageBase: 0x140000000
   ├── .text section (code)
   └── .rdata section (strings, IAT)

2. Build IAT map
   └── Walk DIRECTORY_ENTRY_IMPORT → address → name

3. Extract strings
   ├── ASCII: regex [\x20-\x7e]{4,} in .rdata
   └── UTF-16: scan for printable UTF-16LE sequences

4. Disassemble .text (capstone, x86-64)
   ├── Find function boundaries (CALL targets)
   ├── Resolve IAT references
   ├── Resolve string references
   └── Emit pseudo-C with annotations

5. Output:
   ├── code_map.json     (function → strings, IAT)
   └── DECOMPRESSED_CODE.c (48,088 lines of pseudo-C)
```

### Key Design Decisions

- **skipdata=True** — don't fail on undecodable bytes
- **Function boundary detection** — collect all CALL targets, sort, split
- **String annotation** — inline string references as comments in output
- **IAT resolution** — replace raw addresses with function names

---

## How to Rebuild / Extend

### Add new format support

1. Study the relevant function in `DECOMPRESSED_CODE.c`
2. Document the format in `EXTRACTED_FINDINGS.md`
3. Implement in Python (see `Python Pseudocode` below)
4. Test against `unpacked/` resources

### Extend the decompiler

1. Modify `full_decompile_all.py`
2. Add new analysis passes (e.g., control flow, data structures)
3. Re-run: `python full_decompile_all.py`

### Integrate with GTAIV_ModKit

The findings from this project power these modules in
[GTAIV_ModKit](https://github.com/do5ee911-lab/GTAIV_ModKit):

| Module | What it uses from this project |
|--------|-------------------------------|
| `rgxa.py` | XOR key16, RGXA format, raw-deflate |
| `tint.py` | FNV hash, tint injection, part classification |
| `wft.py` | WFT structure, inject_tint() |
| `aes.py` | AES-256 key, 16-round ECB |
| `img.py` | vehicles.img format, encryption |

---

## Python Pseudocode

### Full conversion pipeline

```python
def convert_vehicle(wft_bytes, wtd_bytes, target="cft"):
    # 1. Unpack WFT (XOR + RGXA)
    wft_plain = rgxa_unpack(wft_bytes)
    
    # 2. Unpack WTD (XOR + RGXA)
    wtd_plain = rgxa_unpack(wtd_bytes)
    
    # 3. Patch WFT (tint injection + part classification)
    wft_patched = patch_wft(wft_plain)
    
    # 4. Patch WTD (texture conversion)
    wtd_patched = patch_wtd(wtd_plain)
    
    # 5. Run appropriate converter
    if target == "cft":
        run_converter("ivCellConverter.exe", wft_patched, "output.cft")
    elif target == "xft":
        run_converter("ivXenonConverter.exe", wft_patched, "output.xft")
    elif target == "xtd":
        run_converter("ivXtdConverter.exe", wft_patched, "output.xtd")
```

### Tint injection

```python
def inject_tint(dec, shader_offset, tint_color=(1.0, 1.0, 1.0, 1.0)):
    # Rename shaders
    for pos in range(0, len(dec) - 0x60, 0x60):
        name_ptr = struct.unpack_from("<I", dec, pos + 0x14)[0]
        if (name_ptr >> 28) == 5:
            name_off = name_ptr & 0x0FFFFFFF
            name = dec[name_off:dec.find(b'\x00', name_off)].decode()
            replacement = {
                'texturesampler': 'ragex_tint',
                'dirtsampler': 'ragex_tint_zero',
                'specsampler': 'ragex_tint_zero',
            }.get(name.lower())
            if replacement:
                dec[name_off:name_off+len(replacement)+1] = replacement.encode() + b'\x00'
    
    # Inject tint values
    r, g, b, a = tint_color
    struct.pack_into("<ffff", dec, shader_offset + 0x04, r, g, b, a)
```

### Part classification

```python
def classify_part(name):
    low = name.lower()
    if low in {'windscreen', 'windscreen_r', 'window_lf', 'window_rf',
               'window_lr', 'window_rr', 'window_lm', 'window_rm'}:
        return 'glass'
    if low.startswith('misc_') or low.startswith('door_') or low == 'boot':
        return 'door'
    if 'window' in low:
        return 'window'
    if 'glass' in low:
        return 'glass'
    return 'body'
```

---

## License

MIT License — see [LICENSE](LICENSE).

This project is for **research and educational purposes**. The original
converter is by TEAM RageX. Not affiliated with Rockstar Games.

---

## Related Projects

- [GTAIV_ModKit](https://github.com/do5ee911-lab/GTAIV_ModKit) — Full PS3 mod toolkit (archives, vehicles, tint, RGXA)
- [GTAIV_TintKit](https://github.com/do5ee911-lab/GTAIV_ModKit) — Standalone tint/RGXA/classification tool
