import os
import struct

from . import aes

BLOCK = 2048
IMG_MAGIC = 0xA94E2A52


class ImgError(Exception):
    pass


def _align(value, block=BLOCK):
    return (value + block - 1) // block * block


def _resource_words_be(data):
    res_type = struct.unpack_from(">I", data, 4)[0]
    flags = struct.unpack_from(">I", data, 8)[0]
    return res_type, flags


class ImgEntry:
    __slots__ = ("index", "name", "size_or_flags", "res_type", "offset_block",
                 "used_blocks", "flags", "blob")

    def __init__(self, index, name, size_or_flags, res_type, offset_block,
                 used_blocks, flags, blob=None):
        self.index = index
        self.name = name
        self.size_or_flags = size_or_flags
        self.res_type = res_type
        self.offset_block = offset_block
        self.used_blocks = used_blocks
        self.flags = flags
        self.blob = blob

    @property
    def is_resource(self):
        return (self.size_or_flags & 0xC0000000) != 0

    @property
    def padding(self):
        return self.flags & 0x7FF

    @property
    def stored_size(self):
        if self.is_resource:
            return self.used_blocks * BLOCK - self.padding
        return self.size_or_flags


class ImgArchive:
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
        if len(self.data) < 20:
            raise ImgError("file too small: %s" % self.path)
        raw_head = self.data[:16]
        self.encrypted = struct.unpack_from("<I", raw_head, 0)[0] != IMG_MAGIC
        head = aes.decrypt(raw_head) if self.encrypted else raw_head
        ident, version, count, table_size = struct.unpack("<IIII", head)
        if ident != IMG_MAGIC:
            raise ImgError("bad image magic 0x%08X in %s" % (ident, self.path))
        if version != 3:
            raise ImgError("unsupported image version %d in %s" % (version, self.path))
        tail = self.data[16:20]
        if len(tail) != 4:
            raise ImgError("truncated header in %s" % self.path)
        self.ident = ident
        self.kind = "IMG3"
        self.version = version
        self.count = count
        self.table_size = table_size
        self.item_size, self.unknown16 = struct.unpack("<HH", tail)
        raw_table = self.data[20:20 + table_size]
        if len(raw_table) != table_size:
            raise ImgError("truncated table in %s" % self.path)
        table = bytearray(raw_table)
        full = len(table) // 16 * 16
        if full and self.encrypted:
            table[:full] = aes.decrypt(bytes(table[:full]))
        self.table_plain = bytes(table)
        self.raw_table = raw_table
        entries_bytes = count * 16
        if entries_bytes > len(table):
            raise ImgError("table too small in %s" % self.path)
        names_blob = bytes(table[entries_bytes:])
        names = names_blob.split(b"\x00")
        if len(names) < count or any(n == b"" for n in names[:count]):
            raise ImgError("bad names in %s" % self.path)
        self.entries = []
        for i in range(count):
            f0, f1, f2 = struct.unpack_from("<III", table, i * 16)
            used, flags = struct.unpack_from("<HH", table, i * 16 + 12)
            name = names[i].decode("latin-1")
            self.entries.append(ImgEntry(i, name, f0, f1, f2, used, flags))
        self.names_sorted = [e.name for e in self.entries] == sorted(
            e.name for e in self.entries)

    def _start(self, entry):
        return entry.offset_block * BLOCK

    def stored_bytes(self, entry):
        start = self._start(entry)
        size = entry.stored_size
        end = start + size
        if end > len(self.data):
            raise ImgError("entry %s out of bounds" % entry.name)
        return self.data[start:end]

    def read(self, name):
        for e in self.entries:
            if e.name == name:
                return self.stored_bytes(e)
        raise ImgError("no such entry in %s: %s" % (self.path, name))

    def has(self, name):
        return any(e.name == name for e in self.entries)

    def get(self, name):
        for e in self.entries:
            if e.name == name:
                return e
        raise ImgError("no such entry in %s: %s" % (self.path, name))

    def list_names(self):
        return [e.name for e in self.entries]


def _make_entry(name, blob, orig=None, is_add=False):
    if is_resource_blob(blob):
        res_type, flags_word = _resource_words_be(blob)
        stored = blob
        used = _align(len(stored)) // BLOCK
        pad = used * BLOCK - len(stored)
        base = (orig.flags & ~0x7FF) if orig is not None else 0x2000
        entry_flags = base | pad
        return ImgEntry(0, name, flags_word & 0xFFFFFFFF, res_type, 0, used,
                        entry_flags, stored)
    if is_add:
        if orig is not None:
            size_field = orig.size_or_flags
            res_type = orig.res_type
            entry_flags = orig.flags
        else:
            size_field = len(blob)
            res_type = 0
            entry_flags = 0
    else:
        size_field = len(blob)
        res_type = orig.res_type if orig is not None else 0
        entry_flags = orig.flags if orig is not None else 0
    used = _align(len(blob)) // BLOCK
    return ImgEntry(0, name, size_field & 0xFFFFFFFF, res_type, 0, used,
                    entry_flags, blob)


def is_resource_blob(blob):
    return blob[:4] in (b"RSC\x05", bytes([0x05, 0x43, 0x53, 0x52]))


def build(original, replacements=None, additions=None):
    replacements = replacements or {}
    additions = dict(additions or {})
    out = []
    for e in original.entries:
        if e.name in replacements:
            blob = replacements.pop(e.name)
            if is_resource_blob(blob) != e.is_resource:
                kind = "PS3 resource (RSC)" if is_resource_blob(blob) else "normal file"
                want = "a PS3 resource (RSC)" if e.is_resource else "a normal file"
                raise ImgError("%s: replacement must be %s, got %s" %
                               (e.name, want, kind))
            ne = _make_entry(e.name, blob, orig=e)
            ne.index = e.index
            out.append(ne)
        else:
            ne = ImgEntry(e.index, e.name, e.size_or_flags, e.res_type,
                          e.offset_block, e.used_blocks, e.flags,
                          original.stored_bytes(e))
            out.append(ne)
    for name in sorted(additions):
        blob = additions.pop(name)
        if any(e.name == name for e in out):
            raise ImgError("entry already exists: %s" % name)
        ne = _make_entry(name, blob, is_add=True)
        out.append(ne)
    if original.names_sorted:
        out.sort(key=lambda e: e.name)
    for i, e in enumerate(out):
        e.index = i

    has_adds = bool(out) and len(out) != original.count
    if has_adds:
        names = bytearray()
        for e in out:
            names += e.name.encode("latin-1") + b"\x00"
        names = bytes(names)
        table_size = len(out) * 16 + len(names)
    else:
        names = original.table_plain[original.count * 16:]
        table_size = original.table_size
    data_start = _align(20 + table_size)

    table = bytearray()
    cursor = data_start
    for e in out:
        cursor = _align(cursor)
        block = cursor // BLOCK
        if block > 0xFFFFFFFF:
            raise ImgError("archive too large")
        stored = e.blob
        used = _align(len(stored)) // BLOCK
        table += struct.pack("<IIIHH", e.size_or_flags, e.res_type, block,
                             used, e.flags)
        e.offset_block = block
        e.blob = stored
        cursor = block * BLOCK + len(stored)
    table += names
    if len(table) != table_size:
        raise ImgError("table size mismatch %d != %d" % (len(table), table_size))

    table_bytes = bytes(table)
    enc_table = bytearray(table_bytes)
    full = len(enc_table) // 16 * 16
    if full and getattr(original, "encrypted", True):
        enc_table[:full] = aes.encrypt(bytes(enc_table[:full]))

    header_plain = struct.pack("<IIII", original.ident, original.version,
                               len(out), table_size)
    head16 = aes.encrypt(header_plain) if getattr(
        original, "encrypted", True) else header_plain
    tail = struct.pack("<HH", original.item_size, original.unknown16)

    out_data = bytearray(head16 + tail + bytes(enc_table))
    if len(out_data) < data_start:
        out_data += b"\x00" * (data_start - len(out_data))
    end = data_start
    for e in out:
        end = max(end, e.offset_block * BLOCK + len(e.blob))
    if len(out_data) < end:
        out_data += b"\x00" * (end - len(out_data))
    for e in out:
        s = e.offset_block * BLOCK
        out_data[s:s + len(e.blob)] = e.blob
    if len(out_data) < len(original.data):
        out_data += b"\x00" * (len(original.data) - len(out_data))
    return bytes(out_data)


def replace_entries(path, replacements=None, additions=None, out_path=None):
    arc = ImgArchive(path)
    data = build(arc, replacements=replacements, additions=additions)
    if out_path is None:
        out_path = path
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, out_path)
    return out_path
