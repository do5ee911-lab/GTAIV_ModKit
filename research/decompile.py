import pefile, struct, re, sys, json
from capstone import Cs, CS_ARCH_X86, CS_MODE_64
from capstone.x86 import *

PATH = r"C:\Users\_MO\Desktop\14\GTAIV_Converter_by_TEAM_RageX.exe"
pe = pefile.PE(PATH)
data = open(PATH, "rb").read()
IB = pe.OPTIONAL_HEADER.ImageBase
TEXT = next(s for s in pe.sections if s.Name.rstrip(b"\x00") == b".text")
TEXT_RVA, TEXT_SIZE = TEXT.VirtualAddress, TEXT.SizeOfRawData
TEXT_DATA = TEXT.get_data()
RDATA = next(s for s in pe.sections if s.Name.rstrip(b"\x00") == b".rdata")
RDATA_RVA = RDATA.VirtualAddress

def rva2off(rva): return pe.get_offset_from_rva(rva)
def rd(rva, n):
    o = rva2off(rva); return data[o:o+n]

md = Cs(CS_ARCH_X86, CS_MODE_64)
md.detail = True
md.skipdata = True

# imports
IAT = {}
if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
    for e in pe.DIRECTORY_ENTRY_IMPORT:
        for i in e.imports:
            if i.name: IAT[IB + (i.address - IB)] = i.name.decode(errors="replace")
            else: IAT[i.address] = f"ord_{i.ordinal}"

# rebuild IAT properly
IAT = {}
if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
    for e in pe.DIRECTORY_ENTRY_IMPORT:
        for i in e.imports:
            name = i.name.decode(errors="replace") if i.name else f"ord_{i.ordinal}"
            IAT[i.address] = name

# strings
str_ascii, str_utf16 = {}, {}
for m in re.finditer(rb"[\x20-\x7e]{4,}", data):
    try: r = pe.get_rva_from_offset(m.start())
    except Exception: continue
    if r is not None and RDATA_RVA <= r < RDATA_RVA + RDATA.Misc_VirtualSize:
        str_ascii[r] = m.group().decode("ascii")
i = 0
while i < len(data) - 1:
    j = i; chars = []
    while j + 1 < len(data):
        cp = data[j] | (data[j+1] << 8)
        if 0x20 <= cp < 0x7f: chars.append(chr(cp)); j += 2
        else: break
    if len(chars) >= 4:
        try:
            r = pe.get_rva_from_offset(i)
            if r is not None and RDATA_RVA <= r < RDATA_RVA + RDATA.Misc_VirtualSize:
                str_utf16[r] = "".join(chars)
        except Exception: pass
        i = j
    else: i += 2

def get_str(rva):
    if rva in str_utf16: return str_utf16[rva], "utf16"
    if rva in str_ascii: return str_ascii[rva], "ascii"
    return None, None

# function bounds: call targets + prologue after CC
call_targets = set()
i = 0
while i < TEXT_SIZE - 5:
    if TEXT_DATA[i] == 0xE8:
        disp = struct.unpack("<i", TEXT_DATA[i+1:i+5])[0]
        dst = TEXT_RVA + i + 5 + disp
        if TEXT_RVA <= dst < TEXT_RVA + TEXT_SIZE: call_targets.add(dst)
    i += 1
FUNC = set(call_targets)
for p in [bytes.fromhex("4055"), bytes.fromhex("48895c2408"), bytes.fromhex("4883ec"),
          bytes.fromhex("4881ec"), bytes.fromhex("4053"), bytes.fromhex("4154"), bytes.fromhex("4155"),
          bytes.fromhex("4156"), bytes.fromhex("4157"), bytes.fromhex("555657")]:
    start = 0
    while True:
        k = TEXT_DATA.find(p, start)
        if k == -1: break
        if k >= 1 and TEXT_DATA[k-1] == 0xCC:
            FUNC.add(TEXT_RVA + k)
        start = k + 1
FUNC.add(pe.OPTIONAL_HEADER.AddressOfEntryPoint)
FUNC = sorted(FUNC)
FUNCSET = set(FUNC)

def next_func(rva):
    for f in FUNC:
        if f > rva: return f
    return TEXT_RVA + TEXT_SIZE

REG64 = ["rax","rcx","rdx","rbx","rsp","rbp","rsi","rdi","r8","r9","r10","r11","r12","r13","r14","r15"]
REG32 = ["eax","ecx","edx","ebx","esp","ebp","esi","edi","r8d","r9d","r10d","r11d","r12d","r13d","r14d","r15d"]

# ---------- Pseudo-C decompiler ----------
def safe_ops(ins):
    try:
        return list(ins.operands)
    except Exception:
        return []

def decompile_func(start_rva, max_insns=800):
    end = min(next_func(start_rva), start_rva + 0x6000)
    raw = rd(start_rva, end - start_rva)
    insns = list(md.disasm(raw, IB + start_rva))
    lines = []
    # header comment with strings/imports
    strs_here = []
    iats_here = []
    for ins in insns[:400]:
        for op in safe_ops(ins):
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP:
                tgt_rva = (ins.address + ins.size + op.mem.disp) - IB
                s, enc = get_str(tgt_rva)
                if s and s not in strs_here: strs_here.append(s)
                va_tgt = IB + tgt_rva
                if va_tgt in IAT and IAT[va_tgt] not in iats_here:
                    iats_here.append(IAT[va_tgt])
    # find call targets inside
    callees = []
    for ins in insns:
        ops_list = safe_ops(ins)
        if ins.mnemonic == "call" and ops_list and ops_list[0].type == X86_OP_IMM:
            t = ops_list[0].imm - IB
            if t in FUNCSET: callees.append(t)
    # stack frame
    sub_rsp = 0
    pushes = 0
    for ins in insns[:30]:
        if ins.mnemonic == "sub" and "rsp" in ins.op_str and "0x" in ins.op_str:
            try: sub_rsp = int(ins.op_str.split(",")[-1].strip(), 16)
            except: pass
            break
    for ins in insns[:20]:
        if ins.mnemonic == "push": pushes += 1
        elif ins.mnemonic in ("sub",) and "rsp" in ins.op_str: break

    lines.append(f"// ============================================================")
    lines.append(f"// FUNCTION @ RVA {start_rva:#x}  VA {IB+start_rva:#x}  size~{end-start_rva}  frame={sub_rsp:#x} pushes={pushes}")
    if strs_here:
        preview = "; ".join(repr(s[:60]) for s in strs_here[:8])
        lines.append(f"// strings: {preview}")
    if iats_here:
        lines.append(f"// imports: {', '.join(iats_here[:20])}")
    if callees:
        lines.append(f"// calls: {', '.join(hex(c) for c in sorted(set(callees))[:20])}")
    lines.append(f"// ============================================================")
    # signature guess
    lines.append(f"void __fastcall sub_{start_rva:x}(ctx_t* self, uint64_t a2, uint64_t a3, uint64_t a4)")
    lines.append(f"{{")
    # declare stack slots we see
    stack_slots = set()
    for ins in insns:
        for op in safe_ops(ins):
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_RSP and op.mem.disp != 0:
                stack_slots.add(op.mem.disp)
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_RBP and op.mem.disp != 0:
                stack_slots.add(("rbp", op.mem.disp))
    # split rbp/rsp
    rsp_slots = sorted([s for s in stack_slots if isinstance(s, int)])
    rbp_slots = sorted([s for s in stack_slots if isinstance(s, tuple)])
    if rsp_slots:
        lines.append(f"    // stack frame locals")
        for s in rsp_slots[:60]:
            name = f"var_{s:x}" if s >= 0 else f"var_m{-s:x}"
            lines.append(f"    uint64_t  {name};      // [rsp{s:+#x}]")
    for rb, disp in rbp_slots[:40]:
        name = f"vrbp_{disp:x}" if disp >= 0 else f"vrbp_m{-disp:x}"
        lines.append(f"    uint64_t  {name};   // [rbp{disp:+#x}]")

    # simple symbolic pass for readability
    # reg last assignment display
    # pre-scan jump targets for correct label placement
    jump_targets = set()
    for ins in insns:
        if ins.mnemonic in ("je","jne","jz","jnz","ja","jb","jae","jbe","jg","jl","jge","jle","js","jns",
                            "jp","jnp","jmp","jo","jno","jcxz","jecxz","jrcxz"):
            ops_list = safe_ops(ins)
            if ops_list and ops_list[0].type == X86_OP_IMM:
                t = ops_list[0].imm
                if ins.address <= t <= ins.address + 0x10000:
                    jump_targets.add(t)

    lines.append(f"    // ---- code ----")
    cur_label = None
    last_cmp = None  # (opstr_str, immediate, is_test)
    n = 0
    for ins in insns:
        if n >= max_insns:
            lines.append(f"    // ... truncated at {max_insns} insns, total {len(insns)}")
            break
        n += 1
        addr = ins.address
        mn = ins.mnemonic
        ops = ins.op_str
        # label placed at the actual target instruction
        if addr in jump_targets:
            lab = f"loc_{addr - IB:x}"
            lines.append(f"{lab}:")
            cur_label = lab
        # jump
        if mn in ("je","jne","jz","jnz","ja","jb","jae","jbe","jg","jl","jge","jle","js","jns","jp","jnp",
                  "jmp","jo","jno","jcxz","jecxz","jrcxz"):
            ops_list = safe_ops(ins)
            if ops_list and ops_list[0].type == X86_OP_IMM:
                tgt = ops_list[0].imm
                lab = f"loc_{tgt - IB:x}"
                if mn == "jmp":
                    lines.append(f"    goto {lab};                    // {addr:#x}")
                else:
                    # human-readable condition from last cmp/test
                    human = None
                    if last_cmp:
                        kind, a, b = last_cmp
                        if kind == "cmp":
                            imm = None
                            m2 = re.match(r"^-?(?:0x[0-9a-f]+|\d+)$", b)
                            if m2:
                                try: imm = int(b, 16) if b.startswith("0x") else int(b)
                                except: pass
                            if imm is not None:
                                iv = imm
                                rel = {
                                    "je":"==","jz":"==","jne":"!=","jnz":"!=",
                                    "ja":">","jbe":"<=","jb":"<","jae":">=",
                                    "jg":">","jle":"<=","jl":"<","jge":">=",
                                }.get(mn)
                                if rel:
                                    human = f"{a} {rel} {b}"
                        elif kind == "test":
                            rel = {"je":"== 0","jz":"== 0","jne":"!= 0","jnz":"!= 0"}.get(mn)
                            if rel:
                                human = f"({a} & {b}) {rel}"
                    if human:
                        lines.append(f"    if ({human}) goto {lab};      // {mn} @ {addr:#x}")
                    else:
                        cond_map = {
                            "je":"if (ZF)","jne":"if (!ZF)","jz":"if (ZF)","jnz":"if (!ZF)",
                            "ja":"if (CF==0 && ZF==0)","jb":"if (CF)","jae":"if (!CF)","jbe":"if (CF||ZF)",
                            "jg":"if (!ZF && SF==OF)","jl":"if (SF!=OF)","jge":"if (SF==OF)","jle":"if (ZF||SF!=OF)",
                            "js":"if (SF)","jns":"if (!SF)","jp":"if (PF)","jnp":"if (!PF)",
                        }
                        c = cond_map.get(mn, f"if ({mn})")
                        lines.append(f"    if_cond: {c} -> goto {lab};   // {mn} @ {addr:#x}")
                continue
        # calls
        if mn == "call":
            ops_list = safe_ops(ins)
            if ops_list and ops_list[0].type == X86_OP_IMM:
                t = ops_list[0].imm - IB
                if t in FUNCSET:
                    lines.append(f"    sub_{t:x}(self, a2, a3, a4);    // {addr:#x}")
                else:
                    lines.append(f"    call {ops};                    // {addr:#x}")
                continue
        # calls
        if mn == "call":
            ops_list = safe_ops(ins)
            if ops_list and ops_list[0].type == X86_OP_IMM:
                t = ins.operands[0].imm - IB
                if t in FUNCSET:
                    lines.append(f"    sub_{t:x}({ops});              // {addr:#x}")
                else:
                    lines.append(f"    call {ops};                    // {addr:#x}")
                continue
            if "qword ptr [rip" in ops:
                # resolve IAT
                m = re.search(r"rip\s*([+-])\s*0x([0-9a-f]+)", ops)
                if m:
                    sign = 1 if m.group(1)=="+" else -1
                    disp = int(m.group(2),16)*sign
                    tgt = (ins.address + ins.size + disp)
                    name = IAT.get(tgt, f"[{tgt:#x}]")
                    lines.append(f"    {name}(...);                   // {addr:#x} IAT {tgt:#x}")
                    continue
            lines.append(f"    call {ops};                    // {addr:#x}")
            continue
        # lea with string
        if mn == "lea" and "rip" in ops:
            m = re.search(r"rip\s*([+-])\s*0x([0-9a-f]+)", ops)
            if m:
                sign = 1 if m.group(1)=="+" else -1
                disp = int(m.group(2),16)*sign
                tgt = (ins.address + ins.size + disp) - IB
                s, enc = get_str(tgt)
                reg = ops.split(",")[0].strip()
                if s:
                    esc = s.replace("\\","\\\\").replace('"','\\"')
                    lines.append(f"    {reg} = &s_{tgt:x};            // \"{esc[:80]}\" ({enc}) @ {addr:#x}")
                    continue
                if (IB+tgt) in IAT:
                    lines.append(f"    {reg} = &imp_{tgt:x};         // {IAT[IB+tgt]} @ {addr:#x}")
                    continue
        # movdqa/movaps rip loads
        if "rip" in ops and mn.startswith("mov"):
            m = re.search(r"rip\s*([+-])\s*0x([0-9a-f]+)", ops)
            if m:
                sign = 1 if m.group(1)=="+" else -1
                disp = int(m.group(2),16)*sign
                tgt = (ins.address + ins.size + disp) - IB
                s, enc = get_str(tgt)
                dst = ops.split(",")[0].strip()
                if s:
                    esc = s.replace('"','\\"')
                    lines.append(f"    {dst} = s_{tgt:x};             // \"{esc[:80]}\" @ {addr:#x}")
                    continue
                if (IB+tgt) in IAT:
                    lines.append(f"    {dst} = imp_{tgt:x};          // {IAT[IB+tgt]} @ {addr:#x}")
                    continue
                # data blob
                blob = rd(tgt, 16)
                lines.append(f"    {dst} = data_{tgt:x};          // {blob.hex()} @ {addr:#x}")
                continue
        # ret
        if mn == "ret":
            lines.append(f"    return;                        // {addr:#x}")
            continue
        if mn in ("int3",):
            lines.append(f"    /* break */                    // {addr:#x}")
            continue
        # track cmp/test for condition rendering
        if mn == "cmp" and "," in ops:
            a, b = [x.strip() for x in ops.split(",", 1)]
            last_cmp = ("cmp", a, b)
        elif mn == "test" and "," in ops:
            a, b = [x.strip() for x in ops.split(",", 1)]
            last_cmp = ("test", a, b)
        # generic
        # annotate immediates that are interesting
        note = ""
        if mn in ("cmp","mov","movzx","movsx") and "0x" in ops:
            imm_m = re.findall(r"0x([0-9a-fA-F]+)", ops)
            for h in imm_m:
                v = int(h, 16)
                # ascii as imm
                try:
                    b = struct.pack("<I", v & 0xFFFFFFFF)
                    if all(32 <= x < 127 for x in b):
                        note = f'  // "{b.decode("ascii")}"'
                except: pass
        lines.append(f"    {mn:6s} {ops};{' '*(max(1,40-len(ops)))} // {addr:#x}{note}")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)

# ---------------- FULL DECOMPILATION SET ----------------
# Key functions identified by string map
KEY_FUNCS = [
    0x6510,   # WinMain / entry UI
    0x5010,   # Window create / layout
    0x22b0,   # WndProc main
    0x2ce0,   # timer convert trigger
    0x8080,   # WFT pipeline
    0xbc90,   # CreateProcess runner
    0xcc00,   # output inspect
    0xd1c0,   # temp workspace
    0xd640,   # converter dispatcher
    0xfee0,   # crypto helper?
    0x101b0,  # AES archive load
    0x11ca0,
    0x1242a,  # AES encrypt save
    0x20340,  # shader tint
    0x21630,  # drawable names
    0x33f90,  # RGXA resource loader
    0x36d40,  # texconv prep
    0x377c0,  # texconv exec
    0x34900,  # WTD
    0x387b0,  # CTD
    0x28540,  # alloc/decompress?
    pe.OPTIONAL_HEADER.AddressOfEntryPoint,
]

# all functions that reference strings or imports (from code_map.json)
_cm = {"str_by_func": {}, "iat_by_func": {}}
try:
    _cm = json.load(open(r"C:\Users\_MO\Desktop\14\code_map.json", encoding="utf-8"))
    interesting = set(int(x) for x in _cm["str_by_func"].keys()) | set(int(x) for x in _cm["iat_by_func"].keys())
except Exception:
    interesting = set()
full_set = sorted(set(KEY_FUNCS) | (interesting & set(FUNCSET)))

out_path = r"C:\Users\_MO\Desktop\14\DECOMPRESSED_CODE.c"
with open(out_path, "w", encoding="utf-8") as out:
    out.write(r"""/* ==========================================================================
 *  GTAIV_Converter_by_TEAM_RageX.exe  -  AUTOMATIC PSEUDO-C DECOMPILATION
 *  Generator: custom capstone-based decompiler (decompile.py)
 *  Target:    PE32+ x64, MSVC 14.44 (v143), ImageBase 0x140000000
 *  Section:   .text RVA 0x1000 size 0x6a766 | EP RVA 0x45494
 *
 *  Legend:
 *    sub_XXXX()        - internal function (RVA in name)
 *    s_XXXX            - string constant (defined in header)
 *    imp_XXXX          - imported API via IAT
 *    loc_XXXX          - code label (RVA)
 *    // 0x1400xxxxx    - virtual address of the instruction
 * ========================================================================== */
#include <stdint.h>
#include <windows.h>

typedef struct ctx_t ctx_t;
typedef int64_t  (__fastcall *fn_i64)(void*, uint64_t, uint64_t, uint64_t);
typedef int32_t  (__fastcall *fn_i32)(void*, uint64_t, uint64_t, uint64_t);
typedef void     (__fastcall *fn_void)(void*, uint64_t, uint64_t, uint64_t);

/* ---- string aliases (auto-extracted, UTF-8 escaped) ---- */
""")
    # emit string aliases for used rvas across full set
    used_str = {}
    for start in full_set:
        end = min(next_func(start), start+0x4000)
        raw = rd(start, end-start)
        for ins in md.disasm(raw, IB+start):
            if "rip" in ins.op_str and ins.mnemonic in ("lea","mov","movdqa","movaps","movups"):
                m = re.search(r"rip\s*([+-])\s*0x([0-9a-f]+)", ins.op_str)
                if m:
                    sign = 1 if m.group(1)=="+" else -1
                    disp = int(m.group(2),16)*sign
                    tgt = (ins.address+ins.size+disp)-IB
                    s,enc = get_str(tgt)
                    if s: used_str[tgt]=s
    for rva_s, s in sorted(used_str.items()):
        esc = s.replace("\\","\\\\").replace('"','\\"').replace("\n","\\n").replace("\r","")
        out.write(f'static const char     s_{rva_s:x}[] = "{esc[:220]}";\n')

    out.write("\n/* ========================================================================== */\n")
    out.write(f"/* PART 1 - FULL DECOMPILE: {len(full_set)} functions with strings/imports    */\n")
    out.write("/* ========================================================================== */\n\n")
    for start in full_set:
        code = decompile_func(start, max_insns=950)
        out.write(code)
        out.write("\n")

# ---------- PART 2: registry of ALL functions ----------
def func_header(rva):
    end = next_func(rva)
    size = end - rva
    strs = m_str = _cm["str_by_func"].get(str(rva), [])
    iats = _cm["iat_by_func"].get(str(rva), [])
    # callers
    return size, [s for _, s in strs], [s for _, s in iats]

with open(out_path, "a", encoding="utf-8") as out:
    out.write("\n")
    out.write("/* ========================================================================== */\n")
    out.write(f"/* PART 2 - FUNCTION REGISTRY: all {len(FUNC)} identified functions            */\n")
    out.write("/* ========================================================================== */\n")
    out.write("/*\n")
    out.write("%-10s %-8s %-6s  %-60s %s\n" % ("RVA", "VA", "SIZE", "STRINGS (first)", "IMPORTS"))
    out.write("-"*180 + "\n")
    for rva in FUNC:
        try:
            size, strs, iats = func_header(rva)
        except Exception:
            size, strs, iats = 0, [], []
        s_prev = "; ".join(x[:40] for x in strs[:3])
        i_prev = ", ".join(iats[:8])
        out.write("%-10s %-8x %-6d  %-60s %s\n" % (hex(rva), rva, size, s_prev[:60], i_prev))
    out.write("*/\n")

print(f"Wrote {out_path}", file=sys.stderr)
print(f"Full decompile: {len(full_set)} funcs | Registry: {len(FUNC)} funcs", file=sys.stderr)
import os
print(f"Size: {os.path.getsize(out_path)} bytes", file=sys.stderr)
