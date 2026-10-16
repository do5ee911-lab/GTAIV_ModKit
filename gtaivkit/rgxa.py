import struct
import zlib

XOR_KEY16 = bytes.fromhex("9e3bd74261ca158f2db074e9531ca6f8")
RGXA_MAGIC = 0x41584752
RGXA_MAGIC_BYTES = b"RGXA"


def xor_crypt(data):
    out = bytearray(data)
    for i in range(len(out)):
        mixed = ((i * 0x1F + 7) & 0xFF) ^ XOR_KEY16[i & 0xF]
        out[i] ^= mixed
    return bytes(out)


def pack_rgxa(raw):
    if len(raw) % 16 != 0:
        pad = 16 - (len(raw) % 16)
        raw = raw + b"\x00" * pad
    compressed = zlib.compressobj(9, zlib.DEFLATED, -15)
    comp = compressed.compress(raw) + compressed.flush()
    header = struct.pack("<II", RGXA_MAGIC, len(raw))
    payload = header + comp
    if len(payload) % 16 != 0:
        pad = 16 - (len(payload) % 16)
        payload = payload + b"\x00" * pad
    return xor_crypt(payload)


def unpack_rgxa(data):
    if len(data) < 8:
        raise ValueError("RGXA data too small")
    header = xor_crypt(data[:16])
    magic, raw_size = struct.unpack("<II", header[:8])
    if magic != RGXA_MAGIC:
        raise ValueError("bad RGXA magic 0x%08X" % magic)
    payload = xor_crypt(data)
    try:
        result = zlib.decompress(payload[8:], -15)
    except zlib.error:
        result = zlib.decompress(payload[8:])
    if len(result) < raw_size:
        raise ValueError("RGXA decompressed size mismatch: %d < %d" % (len(result), raw_size))
    return result[:raw_size]


def is_rgxa(data):
    if len(data) < 16:
        return False
    try:
        header = xor_crypt(data[:16])
        magic = struct.unpack("<I", header[:4])[0]
        return magic == RGXA_MAGIC
    except Exception:
        return False
