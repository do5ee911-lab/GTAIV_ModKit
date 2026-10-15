import os
import struct
import zlib

from . import aes

BLOCK = 2048
TOC_OFFSET = 2048
RSC_MAGICS = (b"RSC\x05", bytes([0x05, 0x43, 0x53, 0x52]))


class RpfError(Exception):
    pass


def is_resource_magic(data):
    return data[:4] in RSC_MAGICS


def _align(value, block=BLOCK):
    return (value + block - 1) // block * block


class Entry:
    __slots__ = ("index", "is_dir", "name_off", "raw_name", "flags", "index_in",
                 "count", "size", "offset", "temp", "path", "parent")

    def __init__(self, index):
        self.index = index
        self.is_dir = False
        self.name_off = 0
        self.flags = 0
        self.index_in = 0
        self.count = 0
        self.size = 0
        self.offset = 0
        self.temp = 0
        self.path = None
        self.parent = None

    @property
    def is_resource(self):
        return (not self.is_dir) and (self.temp & 0xC0000000) == 0xC0000000

    @property
    def is_compressed(self):
        return (not self.is_dir) and (not self.is_resource) and (self.temp & 0x40000000) != 0

    @property
    def resource_type(self):
        return self.offset & 0xFF if self.is_resource else 0

    @property
    def data_offset(self):
        if self.is_dir:
            return 0
        return self.offset & 0x7FFFFF00 if self.is_resource else self.offset

    @property
    def stored_size(self):
        if self.is_dir:
            return 0
        if self.is_resource:
            return self.size
        return self.temp & 0xBFFFFFFF


class RpfArchive:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as fh:
            self.data = fh.read()
        self._parse()

    @classmethod
    def from_bytes(cls, data, name="<memory>"):
        arc = cls.__new__(cls)
        arc.path = name
        arc.data = data
        arc._parse()
        return arc

    def _parse(self):
        magic, toc_size, entry_count, self.unknown, self.encrypted = struct.unpack_from(
            "<4siiii", self.data, 0)
        if magic not in (b"RPF2", b"RPF3"):
            raise RpfError("bad magic %r in %s" % (magic, self.path))
        if toc_size < 0 or entry_count < 0:
            raise RpfError("bad header in %s" % self.path)
        self.magic = magic
        self.kind = magic.decode("ascii")
        self.is_v3 = magic == b"RPF3"
        raw = self.data[TOC_OFFSET:TOC_OFFSET + toc_size]
        if len(raw) != toc_size:
            raise RpfError("truncated toc in %s" % self.path)
        if toc_size % 16 != 0:
            raise RpfError("toc size not multiple of 16 in %s" % self.path)
        self.toc_size = toc_size
        self.entry_count = entry_count
        toc = aes.decrypt(raw) if self.encrypted else raw
        self.toc_plain = toc
        self.entries = [Entry(i) for i in range(entry_count)]
        for i, e in enumerate(self.entries):
            f0, f1, f2, f3 = struct.unpack_from("<iiii", toc, i * 16)
            if self.is_v3:
                e.name_off = f0 & 0xFFFFFFFF
            else:
                e.name_off = f0
            if f2 < 0:
                e.is_dir = True
                e.flags = f1
                e.index_in = f2 & 0x7FFFFFFF
                e.count = f3 & 0x0FFFFFFF
                e.temp = f3 & 0xFFFFFFFF
            else:
                e.size = f1
                e.offset = f2
                e.temp = f3 & 0xFFFFFFFF
        names_off = entry_count * 16
        self.names_blob = toc[names_off:]
        self._name_cache = {}

        def get_name(off):
            if self.is_v3:
                from . import hashnames
                return hashnames.resolve(off)
            if off in self._name_cache:
                return self._name_cache[off]
            end = toc.find(b"\x00", names_off + off)
            if end < 0:
                raise RpfError("unterminated name at %d in %s" % (off, self.path))
            s = toc[names_off + off:end].decode("latin-1")
            self._name_cache[off] = s
            return s

        if not self.entries:
            raise RpfError("empty archive %s" % self.path)
        root = self.entries[0]
        if not root.is_dir:
            raise RpfError("root is not a directory in %s" % self.path)
        self.root = root
        root.path = "/"
        root.raw_name = get_name(root.name_off)
        self.by_path = {}
        self.file_paths = []
        self.dir_paths = []
        stack = [(root, "")]
        seen = set([0])
        while stack:
            d, prefix = stack.pop()
            for j in range(d.index_in, d.index_in + d.count):
                if j >= entry_count or j in seen:
                    raise RpfError("bad entry index %d in %s" % (j, self.path))
                seen.add(j)
                e = self.entries[j]
                name = get_name(e.name_off)
                e.raw_name = name
                e.parent = d
                e.path = prefix + "/" + name if prefix else name
                if e.is_dir:
                    self.dir_paths.append(e.path)
                    stack.append((e, e.path))
                else:
                    self.file_paths.append(e.path)
                    self.by_path[e.path] = e
        if len(seen) != entry_count:
            raise RpfError("%d of %d entries unreachable in %s" %
                           (entry_count - len(seen), entry_count, self.path))
        self.file_paths.sort()
        self.dir_paths.sort()

    def has(self, path):
        return path.lstrip("/") in self.by_path

    def get(self, path):
        path = path.lstrip("/")
        if path not in self.by_path:
            raise RpfError("no such file in archive: %s" % path)
        return self.by_path[path]

    def stored_bytes(self, entry):
        start = entry.data_offset
        end = start + entry.stored_size
        if end > len(self.data):
            raise RpfError("entry %s out of bounds" % entry.path)
        return self.data[start:end]

    def read_entry(self, entry):
        blob = self.stored_bytes(entry)
        if entry.is_resource:
            return blob
        if entry.is_compressed:
            try:
                out = zlib.decompress(blob, -15)
            except zlib.error as exc:
                raise RpfError("deflate failed for %s: %s" % (entry.path, exc))
            if len(out) != entry.size:
                raise RpfError("size mismatch for %s: %d != %d" %
                               (entry.path, len(out), entry.size))
            return out
        return blob

    def read(self, path):
        return self.read_entry(self.get(path))

    def list_files(self):
        return list(self.file_paths)

    def list_dirs(self):
        return list(self.dir_paths)


def _resource_words(data):
    res_type = struct.unpack_from("<I", data, 4)[0]
    flags = struct.unpack_from("<I", data, 8)[0]
    return res_type, flags


def build(original, replacements, compress=None):
    encrypt_toc = bool(original.encrypted)
    entry_count = len(original.entries)
    name_offs = [entry.name_off for entry in original.entries]
    names = original.toc_plain[entry_count * 16:]
    toc_size = original.toc_size
    data_start = TOC_OFFSET + toc_size

    out_entries = []
    spans = []
    cursor = data_start
    for entry in original.entries:
        if entry.is_dir:
            out_entries.append((name_offs[entry.index], entry.flags,
                                entry.index_in, entry.temp, True))
            continue
        repl = replacements.get(entry.path)
        if repl is None:
            stored = original.stored_bytes(entry)
            was_resource = entry.is_resource
            was_compressed = entry.is_compressed
            res_type = entry.resource_type
            res_flags = entry.temp
            uncomp_size = entry.size
        elif entry.is_resource:
            if not is_resource_magic(repl):
                raise RpfError(
                    "%s is a resource file: replacement must be a PS3 resource "
                    "starting with RSC magic, got %r" % (entry.path, repl[:4]))
            stored = repl
            was_resource = True
            was_compressed = False
            res_type, res_flags = _resource_words(repl)
            uncomp_size = len(repl)
        else:
            if is_resource_magic(repl):
                raise RpfError(
                    "%s is a normal file: replacement must not be an RSC "
                    "resource" % entry.path)
            was_resource = False
            use_deflate = entry.is_compressed if compress is None else (compress == "deflate")
            if use_deflate:
                stored = zlib.compress(repl, 9)[2:-4]
                was_compressed = True
                res_flags = (len(stored) | 0x40000000) & 0xFFFFFFFF
            else:
                stored = repl
                was_compressed = False
                res_flags = len(stored) & 0xFFFFFFFF
            res_type = 0
            uncomp_size = len(repl)
        if was_resource:
            start = _align(cursor)
            offset_field = start | (res_type & 0xFF)
        else:
            aligned = _align(cursor)
            start = aligned if (aligned - cursor) < uncomp_size else cursor
            offset_field = start
        out_entries.append((name_offs[entry.index], uncomp_size, offset_field,
                            res_flags, False))
        spans.append((start, stored))
        cursor = start + len(stored)

    toc = bytearray()
    for item in out_entries:
        if item[4]:
            noff, flags, idx, cnt, _ = item
            toc += struct.pack("<IiII", noff & 0xFFFFFFFF, flags,
                               idx | 0x80000000, cnt & 0xFFFFFFFF)
        else:
            noff, size, offset_field, temp, _ = item
            toc += struct.pack("<IiII", noff & 0xFFFFFFFF, size,
                               offset_field & 0xFFFFFFFF,
                               temp & 0xFFFFFFFF)
    toc += names
    if len(toc) != toc_size:
        raise RpfError("toc size mismatch %d != %d" % (len(toc), toc_size))
    toc_bytes = aes.encrypt(bytes(toc)) if encrypt_toc else bytes(toc)

    header = struct.pack("<4siiii", original.magic, toc_size, len(original.entries),
                         original.unknown, original.encrypted)
    head_tail = original.data[20:TOC_OFFSET]
    out = bytearray(header + head_tail)
    if len(out) < TOC_OFFSET:
        out += b"\x00" * (TOC_OFFSET - len(out))
    out = out[:TOC_OFFSET]
    out += toc_bytes
    end = TOC_OFFSET + toc_size
    for start, blob in spans:
        end = max(end, start + len(blob))
    if len(out) < end:
        out += b"\x00" * (end - len(out))
    for start, blob in spans:
        out[start:start + len(blob)] = blob
    if len(out) < len(original.data):
        out += b"\x00" * (len(original.data) - len(out))
    return bytes(out[:max(end, len(original.data))])


def replace_files(path, replacements, out_path=None, compress=None):
    arc = RpfArchive(path)
    data = build(arc, replacements, compress=compress)
    if out_path is None:
        out_path = path
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, out_path)
    return out_path
