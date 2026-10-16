import pefile, struct, re, json, sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

PATH = r"C:\Users\_MO\Desktop\14\GTAIV_Converter_by_TEAM_RageX.exe"
pe = pefile.PE(PATH)
data = open(PATH, "rb").read()
IB = pe.OPTIONAL_HEADER.ImageBase
TEXT = next(s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text")
TEXT_RVA, TEXT_RAW, TEXT_SIZE = TEXT.VirtualAddress, TEXT.PointerToRawData, TEXT.SizeOfRawData
TEXT_DATA = TEXT.get_data()
RDATA = next(s for s in pe.sections if s.Name.rstrip(b"\x00") == b".rdata")
RDATA_RVA, RDATA_RAW = RDATA.VirtualAddress, RDATA.PointerToRawData

def rva2off(rva): return pe.get_offset_from_rva(rva)
def off2rva(off): return pe.get_rva_from_offset(off)
def va(rva): return IB + rva
def rd(rva, n): 
    o = rva2off(rva)
    return data[o:o+n]

md = Cs(CS_ARCH_X86, CS_MODE_64); md.skipdata = True
md.detail = True

# ---------------- 1. Import map ----------------
imports = {}
if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
    for e in pe.DIRECTORY_ENTRY_IMPORT:
        dll = e.dll.decode(errors="replace")
        for i in e.imports:
            name = i.name.decode(errors="replace") if i.name else f"ord_{i.ordinal}"
            imports[i.address] = f"{name}"
IAT = imports

# ---------------- 2. String table ----------------
# ASCII strings with RVA
str_ascii = {}
for m in re.finditer(rb"[\x20-\x7e]{4,}", TEXT_DATA if False else data):
    off = m.start()
    try:
        r = off2rva(off)
    except Exception:
        continue
    if r is None: continue
    if not (RDATA_RVA <= r < RDATA_RVA + RDATA.Misc_VirtualSize or TEXT_RVA <= r < TEXT_RVA + TEXT_SIZE):
        continue
    str_ascii[r] = m.group().decode("ascii")
# UTF-16 strings
str_utf16 = {}
i = 0
while i < len(data) - 1:
    j = i; chars = []
    while j + 1 < len(data):
        cp = data[j] | (data[j+1] << 8)
        if 0x20 <= cp < 0x7f: chars.append(chr(cp)); j += 2
        else: break
    if len(chars) >= 4:
        try:
            r = off2rva(i)
            if r is not None and (RDATA_RVA <= r < RDATA_RVA + RDATA.Misc_VirtualSize):
                str_utf16[r] = "".join(chars)
        except Exception: pass
        i = j
    else:
        i += 2

print(f"# strings ascii={len(str_ascii)} utf16={len(str_utf16)}", file=sys.stderr)

# ---------------- 3. Function discovery ----------------
# Scan .text for MSVC prologues and int3 gaps
funcs = set()
# common prologues: 40 55 (push rbp), 48 89 5c 24, 48 83 ec, 40 53, 48 89 5c, 55 56 57 etc.
# We use: call targets + prologue at padding boundaries
call_targets = set()

# First pass: find all E8/E9 relative calls/jmps within .text and FF15/FF25 IAT
i = 0
while i < TEXT_SIZE - 5:
    b = TEXT_DATA[i]
    # E8 call rel32
    if b == 0xE8:
        disp = struct.unpack("<i", TEXT_DATA[i+1:i+5])[0]
        src_rva = TEXT_RVA + i
        dst_rva = (src_rva + 5 + disp)
        if TEXT_RVA <= dst_rva < TEXT_RVA + TEXT_SIZE:
            call_targets.add(dst_rva)
        i += 1; continue
    i += 1

# Prologue scan: pattern at byte boundaries likely function starts
prologues = [
    bytes.fromhex("4055"),                 # push rbp
    bytes.fromhex("48895c2408"),           # mov [rsp+8], rbx
    bytes.fromhex("48895c240857"),         # mov [rsp+8],rbx; push rdi
    bytes.fromhex("4883ec"),               # sub rsp, imm8
    bytes.fromhex("4881ec"),               # sub rsp, imm32
    bytes.fromhex("4053"),                 # push rbx
    bytes.fromhex("4056"),                 # push rsi
    bytes.fromhex("4057"),                 # push rdi
    bytes.fromhex("555657"),               # push rbp; push rsi; push rdi
    bytes.fromhex("48895c24"),             # mov [rsp+x], rbx
    bytes.fromhex("4c894c24"),             # mov [rsp+x], r9
    bytes.fromhex("488bec"),               # mov rbp, rsp (less common)
    bytes.fromhex("488da424"),             # lea rsp, [rsp+...]
    bytes.fromhex("4154"),                 # push r12
    bytes.fromhex("4155"),                 # push r13
    bytes.fromhex("4156"),                 # push r14
    bytes.fromhex("4157"),                 # push r15
]
# also function ends: int3 (CC) runs
func_starts = set(call_targets)
for p in prologues:
    start = 0
    while True:
        k = TEXT_DATA.find(p, start)
        if k == -1: break
        # context check: preceded by CC or 90 or another ret/end, or is call target
        if k >= 1 and (TEXT_DATA[k-1] in (0xCC, 0x90, 0xC3, 0xC2) or (k-1) in [t - TEXT_RVA for t in call_targets][:0]):
            func_starts.add(TEXT_RVA + k)
        elif k == 0:
            func_starts.add(TEXT_RVA + k)
        start = k + 1

# filter: must look like code (not inside data) - all in .text anyway
# Also add entry point
func_starts.add(pe.OPTIONAL_HEADER.AddressOfEntryPoint)
# TLS callbacks
print(f"# candidate function starts: {len(func_starts)}", file=sys.stderr)

# Refine: sort and drop starts that are inside previous "likely function" only if clearly mid-function
# Keep it simple: keep all call targets + prologue-after-CC
refined = set(call_targets)
for s in func_starts:
    off = s - TEXT_RVA
    if 0 <= off < TEXT_SIZE and off >= 1 and TEXT_DATA[off-1] == 0xCC:
        refined.add(s)
refined.add(pe.OPTIONAL_HEADER.AddressOfEntryPoint)
FUNC = sorted(refined)
print(f"# refined functions: {len(FUNC)}", file=sys.stderr)

# ---------------- 4. String xrefs (LEA reg,[rip+disp]) ----------------
# Build map: function_rva -> set of string rvas referenced
str_xrefs = {}
leas = []  # (site_rva, target_rva)
i = 0
while i < TEXT_SIZE - 7:
    # REX + 8D /r with modrm 05 (RIP-rel) : 48/4C/49/4D 8D xx disp32
    if TEXT_DATA[i] in (0x48, 0x4C, 0x49, 0x4D, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47) and TEXT_DATA[i+1] == 0x8D:
        modrm = TEXT_DATA[i+2]
        if (modrm & 0xC7) == 0x05:  # RIP-relative
            disp = struct.unpack("<i", TEXT_DATA[i+3:i+7])[0]
            src = TEXT_RVA + i
            nxt = src + 7
            tgt = nxt + disp
            if 0 <= tgt < pe.OPTIONAL_HEADER.SizeOfImage:
                leas.append((src, tgt))
            i += 7; continue
    # 8D without rex
    if TEXT_DATA[i] == 0x8D:
        modrm = TEXT_DATA[i+1]
        if (modrm & 0xC7) == 0x05:
            disp = struct.unpack("<i", TEXT_DATA[i+2:i+6])[0]
            src = TEXT_RVA + i
            tgt = src + 6 + disp
            leas.append((src, tgt))
            i += 6; continue
    i += 1

def func_of(rva):
    # binary search greatest FUNC <= rva
    lo, hi = 0, len(FUNC)-1
    ans = None
    while lo <= hi:
        mid = (lo+hi)//2
        if FUNC[mid] <= rva:
            ans = FUNC[mid]; lo = mid+1
        else:
            hi = mid-1
    return ans

str_by_func = {}
for src, tgt in leas:
    if tgt in str_ascii or tgt in str_utf16:
        f = func_of(src)
        if f is None: continue
        s = str_ascii.get(tgt) or str_utf16.get(tgt)
        str_by_func.setdefault(f, set()).add((src, s))

# IAT call xrefs by function
iat_by_func = {}
i = 0
while i < TEXT_SIZE - 6:
    if TEXT_DATA[i] == 0xFF and TEXT_DATA[i+1] in (0x15, 0x25):
        disp = struct.unpack("<i", TEXT_DATA[i+2:i+6])[0]
        src = TEXT_RVA + i
        tgt = src + 6 + disp
        tgt_va = IB + tgt
        if tgt_va in IAT:
            f = func_of(src)
            if f: iat_by_func.setdefault(f, set()).add((src, IAT[tgt_va]))
        i += 6; continue
    i += 1

# Save metadata
meta = {
    "funcs": FUNC,
    "imports_count": len(IAT),
    "str_by_func": {str(k): sorted(list(v))[:40] for k, v in str_by_func.items()},
    "iat_by_func": {str(k): sorted(list(v))[:60] for k, v in iat_by_func.items()},
}
with open(r"C:\Users\_MO\Desktop\14\code_map.json", "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=1)
print(f"# functions with strings: {len(str_by_func)}, with imports: {len(iat_by_func)}", file=sys.stderr)
print(f"# total funcs {len(FUNC)}")
