"""Resolve GTA IV RPF3 entry-name hashes.

The hash table ships with pyrpfiv (MIT, copyright gmroder) as hashes.ini and
maps the unsigned 32-bit hash stored in every RPF3 TOC entry to a filename.
"""
import os
import sys

_HASHES = None


def _candidate_paths():
    here = os.path.dirname(os.path.abspath(__file__))
    yield os.path.join(here, "hashes.ini")
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        yield os.path.join(mei, "gtaivkit", "hashes.ini")


def _load():
    for path in _candidate_paths():
        if not os.path.isfile(path):
            continue
        table = {}
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("[") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                try:
                    table[int(key)] = value
                except ValueError:
                    continue
        return table
    return {}


def resolve(name_hash):
    global _HASHES
    if _HASHES is None:
        _HASHES = _load()
    value = name_hash & 0xFFFFFFFF
    return _HASHES.get(value) or ("0x%08X" % value)
