import struct
import zlib

MAGIC_PC = b"RSC\x05"
MAGIC_PS3 = bytes([5, 67, 83, 82])

TYPE_MODEL_PC = 112
TYPE_MODEL_PS3 = 117
TYPE_TEXTURE_PC = 8
TYPE_TEXTURE_PS3 = 7

SEG_SYSTEM = 5
SEG_GPU = 6


class RscError(Exception):
    pass


def swap_u32(v):
    v &= 0xFFFFFFFF
    return ((v & 0xFF) << 24) | ((v & 0xFF00) << 8) | ((v >> 8) & 0xFF00) | (v >> 24)


def compact_size(size):
    size &= 0xFFFFFFFF
    if size % 256 != 0:
        size = (size // 256 + 1) * 256
    size >>= 8
    num = 0
    while (size & 1) == 0 and size >= 32 and num < 15:
        num += 1
        size >>= 1
    return ((num & 0xF) << 11) | (size & 0x7FF)


def _size_encodes_exactly(size):
    num = compact_size(size)
    shift = (num >> 11) & 0xF
    encoded = (num & 0x7FF) << (shift + 8)
    rounded = size
    if rounded % 256 != 0:
        rounded = (rounded // 256 + 1) * 256
    return encoded == rounded


def pad_size_for_flags(size):
    num = size & 0xFFFFFFFF
    if num % 256 != 0:
        num = (num // 256 + 1) * 256
    if _size_encodes_exactly(num):
        return num
    num2 = (num + 65535) & 0xFFFF0000
    if num2 < num:
        num2 = num + 65536
    for _ in range(64):
        if _size_encodes_exactly(num2):
            return num2
        num2 += 65536
    return num2


def encode_flags(sys_size, gpu_size):
    return (compact_size(sys_size) & 0x7FFF) | \
           ((compact_size(gpu_size) & 0x7FFF) << 15) | 0xC0000000


def decode_flags(flags):
    sys_size = (flags & 0x7FF) << (((flags >> 11) & 0xF) + 8)
    gpu_size = ((flags >> 15) & 0x7FF) << (((flags >> 26) & 0xF) + 8)
    return sys_size, gpu_size


def make_ptr(offset, seg_type):
    return (offset & 0xFFFFFFF) | (seg_type << 28)


def ptr_offset(ptr):
    return ptr & 0xFFFFFFF


def ptr_type(ptr):
    return ptr >> 28


def hash_name(name):
    h = 0
    for c in (name or "").lower():
        h = (h + ord(c)) & 0xFFFFFFFF
        h = (h + ((h << 10) & 0xFFFFFFFF)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + ((h << 3) & 0xFFFFFFFF)) & 0xFFFFFFFF
    h ^= h >> 11
    return (h + ((h << 15) & 0xFFFFFFFF)) & 0xFFFFFFFF


def _inflate(payload):
    try:
        return zlib.decompress(payload)
    except zlib.error:
        pass
    for wbits in (-15, 15):
        try:
            return zlib.decompress(payload[2:], wbits)
        except zlib.error:
            continue
    try:
        return zlib.decompress(payload)
    except zlib.error as exc:
        raise RscError("zlib decompress failed: %s" % exc)


class RscFile:
    __slots__ = ("is_ps3", "type", "flags", "payload", "decompressed", "raw")

    def __init__(self):
        self.is_ps3 = False
        self.type = 0
        self.flags = 0
        self.payload = b""
        self.decompressed = b""
        self.raw = b""

    @property
    def system_size(self):
        return decode_flags(self.flags)[0]

    @property
    def gpu_size(self):
        return decode_flags(self.flags)[1]

    @classmethod
    def load(cls, path):
        with open(path, "rb") as fh:
            return cls.from_bytes(fh.read(), path)

    @classmethod
    def from_bytes(cls, data, name="<memory>"):
        if len(data) < 12:
            raise RscError("RSC too small in %s" % name)
        self = cls()
        self.raw = data
        if data[:4] == MAGIC_PS3:
            self.is_ps3 = True
            self.type = swap_u32(struct.unpack_from("<I", data, 4)[0])
            self.flags = swap_u32(struct.unpack_from("<I", data, 8)[0])
        elif data[:4] == MAGIC_PC:
            self.is_ps3 = False
            self.type = struct.unpack_from("<I", data, 4)[0]
            self.flags = struct.unpack_from("<I", data, 8)[0]
        else:
            raise RscError("bad RSC magic %r in %s" % (data[:4], name))
        self.payload = data[12:]
        self.decompressed = _inflate(self.payload)
        return self

    def build_ps3(self, type_=None, sys_size=None, gpu_size=None):
        if type_ is None:
            type_ = self.type if not self.is_ps3 else self.type
        if sys_size is None and gpu_size is None:
            flags = encode_flags(self.system_size, self.gpu_size)
        else:
            flags = encode_flags(sys_size, gpu_size)
        blob = zlib.compress(self.decompressed, 9)
        return MAGIC_PS3 + struct.pack(">II", type_ & 0xFFFFFFFF, flags) + blob

    def build_pc(self, type_=None):
        if type_ is None:
            type_ = self.type
        blob = zlib.compress(self.decompressed, 9)
        return MAGIC_PC + struct.pack("<II", type_ & 0xFFFFFFFF, self.flags) + blob
