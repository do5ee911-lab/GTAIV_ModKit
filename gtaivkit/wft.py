from .rsc import (RscError, RscFile, TYPE_MODEL_PC, TYPE_MODEL_PS3,
                  decode_flags)
from . import tint as tintmod
import struct


class WftFile:
    __slots__ = ("rsc",)

    def __init__(self, rsc):
        self.rsc = rsc

    @classmethod
    def load(cls, path):
        return cls(RscFile.load(path))

    @classmethod
    def from_bytes(cls, data, name="<memory>"):
        return cls(RscFile.from_bytes(data, name))

    @property
    def is_ps3(self):
        return self.rsc.is_ps3

    @property
    def type(self):
        return self.rsc.type

    @property
    def system_size(self):
        return self.rsc.system_size

    @property
    def gpu_size(self):
        return self.rsc.gpu_size

    @property
    def decompressed(self):
        return self.rsc.decompressed

    def info(self):
        sys_size, gpu_size = decode_flags(self.rsc.flags)
        return {
            "platform": "PS3" if self.rsc.is_ps3 else "PC",
            "type": self.rsc.type,
            "flags": self.rsc.flags,
            "system_size": sys_size,
            "gpu_size": gpu_size,
            "decompressed": len(self.rsc.decompressed),
        }

    def to_ps3(self):
        if self.rsc.is_ps3:
            return self.rsc.raw
        return self.rsc.build_ps3(type_=TYPE_MODEL_PS3)

    def to_pc(self):
        if not self.rsc.is_ps3:
            return self.rsc.raw
        return self.rsc.build_pc(type_=TYPE_MODEL_PC)

    def inject_tint(self, tint_color=(1.0, 1.0, 1.0, 1.0)):
        if self.rsc.is_ps3:
            raise RscError("tint injection is PC-only; convert to PS3 first")
        dec = bytearray(self.rsc.decompressed)
        renamed = tintmod.patch_shader_names(dec, 0, len(dec))
        patched = 0
        for i in range(len(dec) - 0x20):
            if struct.unpack_from("<I", dec, i)[0] == 0xEC896300:
                if tintmod.inject_tint_params(dec, i, tint_color):
                    patched += 1
        self.rsc.decompressed = bytes(dec)
        return {"renamed": renamed, "patched": patched}
