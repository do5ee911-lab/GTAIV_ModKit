# Decompile GTAIV Converter — Extracted Resources

This script extracts and unpacks all embedded resources (RGXA container)
from the original GTA IV converter executable.

```python
import os, struct, zlib

XOR_KEY = bytes.fromhex('9e3bd74261ca158f2db04e9531ca6f8')

def xor_decrypt(data):
    out = bytearray(data)
    for i in range(len(out)):
        mixed = ((i * 0x1F + 7) & 0xFF) ^ XOR_KEY[i & 0xF]
        out[i] ^= mixed
    return bytes(out)

def rgxa_unpack(data):
    dec = xor_decrypt(data)
    magic = struct.unpack('<I', dec[:4])[0]
    if magic != 0x41584752:
        raise ValueError('bad magic')
    raw_size = struct.unpack('<I', dec[4:8])[0]
    return zlib.decompress(dec[8:], -15)[:raw_size]

def extract_resources(exe_path, out_dir):
    import pefile
    pe = pefile.PE(exe_path)
    os.makedirs(out_dir, exist_ok=True)
    names = {
        101: 'ivCellConverter.exe',
        102: 'ivXenonConverter.exe',
        103: 'ivXtdConverter.exe',
        104: 'ragex_texconv.exe',
        105: 'shader_params_gcm.txt',
        106: 'shader_params_xenon.txt',
        107: 'ui_screenshot.png',
    }
    for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        rid = entry.struct.Id
        if rid not in names:
            continue
        for e2 in entry.directory.entries:
            for e3 in e2.directory.entries:
                off = e3.data.struct.OffsetToData
                size = e3.data.struct.Size
                raw = pe.get_memory_mapped_image()[off:off+size]
                plain = rgxa_unpack(raw)
                out = os.path.join(out_dir, names[rid])
                with open(out, 'wb') as f:
                    f.write(plain)
                print(f'  {rid}: {names[rid]} ({len(plain)} bytes)')

if __name__ == '__main__':
    extract_resources('GTAIV_Converter_by_TEAM_RageX.exe', 'unpacked/')
```
