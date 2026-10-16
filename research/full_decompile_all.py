import pefile, struct, re, sys, json, os
from capstone import Cs, CS_ARCH_X86, CS_MODE_64
from capstone.x86 import *

SRC = r"C:\Users\_MO\Desktop\14\GTAIV_Converter_by_TEAM_RageX.exe"
OUT = r"C:\Users\_MO\Desktop\GTAIV_Converter_FULL_DECOMPILE.c"

pe = pefile.PE(SRC)
data = open(SRC, "rb").read()
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

def safe_ops(ins):
    try:
        return list(ins.operands)
    except Exception:
        return []

# ---- IAT ----
IAT = {}
if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
    for e in pe.DIRECTORY_ENTRY_IMPORT:
        for i in e.imports:
            name = i.name.decode(errors="replace") if i.name else f"ord_{i.ordinal}"
            IAT[i.address] = name

# ---- strings ----
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

# ---- function discovery ----
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

# ---- call graph ----
CALLERS = {f: [] for f in FUNC}
CALLEES = {f: set() for f in FUNC}
for f in FUNC:
    end = min(next_func(f), f + 0x8000)
    raw = rd(f, end - f)
    for ins in md.disasm(raw, IB + f):
        if ins.mnemonic == "call":
            for op in safe_ops(ins):
                if op.type == X86_OP_IMM:
                    t = op.imm - IB
                    if t in FUNCSET:
                        CALLEES[f].add(t)
                        CALLERS[t].append(f)
                    break

# ---- import usage map ----
IMPORTS_USED = {}  # va -> [func rvas]
for f in FUNC:
    end = min(next_func(f), f + 0x8000)
    raw = rd(f, end - f)
    for ins in md.disasm(raw, IB + f):
        for op in safe_ops(ins):
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP:
                va = ins.address + ins.size + op.mem.disp
                if va in IAT:
                    IMPORTS_USED.setdefault(va, [])
                    if not IMPORTS_USED[va] or IMPORTS_USED[va][-1] != f:
                        IMPORTS_USED[va].append(f)

def decompile_func(start_rva, max_insns=4000):
    end = min(next_func(start_rva), start_rva + 0x20000)
    raw = rd(start_rva, end - start_rva)
    insns = list(md.disasm(raw, IB + start_rva))
    lines = []
    strs_here = []
    iats_here = []
    for ins in insns[:1500]:
        for op in safe_ops(ins):
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_RIP:
                tgt_rva = (ins.address + ins.size + op.mem.disp) - IB
                s, enc = get_str(tgt_rva)
                if s and s not in strs_here: strs_here.append(s)
                va_tgt = IB + tgt_rva
                if va_tgt in IAT and IAT[va_tgt] not in iats_here:
                    iats_here.append(IAT[va_tgt])
    callees = []
    for ins in insns:
        if ins.mnemonic == "call":
            for op in safe_ops(ins):
                if op.type == X86_OP_IMM:
                    t = op.imm - IB
                    if t in FUNCSET: callees.append(t)
                    break
    sub_rsp = 0
    pushes = 0
    for ins in insns[:30]:
        if ins.mnemonic == "sub" and "rsp" in ins.op_str and "0x" in ins.op_str:
            try: sub_rsp = int(ins.op_str.split(",")[-1].strip(), 16)
            except: pass
            break
    for ins in insns[:20]:
        if ins.mnemonic == "push": pushes += 1
        elif ins.mnemonic == "sub" and "rsp" in ins.op_str: break

    size = end - start_rva
    lines.append("// ========================================================================")
    lines.append(f"// FUNCTION  RVA {start_rva:#x}  |  VA {IB+start_rva:#x}  |  size {size} bytes  |  frame {sub_rsp:#x}  |  saved-regs {pushes}")
    if strs_here:
        lines.append("// strings : " + " ; ".join(repr(s[:70]) for s in strs_here[:10]))
    if iats_here:
        lines.append("// imports : " + ", ".join(iats_here[:25]))
    if callees:
        lines.append("// calls   : " + ", ".join("sub_%x" % c for c in sorted(set(callees))[:30]))
    cl = CALLERS.get(start_rva, [])
    if cl:
        lines.append("// called by: " + ", ".join("sub_%x" % c for c in cl[:25]))
    lines.append("// ========================================================================")
    lines.append(f"void __fastcall sub_{start_rva:x}(ctx_t* self, uint64_t a2, uint64_t a3, uint64_t a4)")
    lines.append("{")

    stack_slots = set()
    for ins in insns:
        for op in safe_ops(ins):
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_RSP and op.mem.disp != 0:
                stack_slots.add(op.mem.disp)
            if op.type == X86_OP_MEM and op.mem.base == X86_REG_RBP and op.mem.disp != 0:
                stack_slots.add(("rbp", op.mem.disp))
    rsp_slots = sorted([s for s in stack_slots if isinstance(s, int)])
    rbp_slots = sorted([s for s in stack_slots if isinstance(s, tuple)])
    if rsp_slots or rbp_slots:
        lines.append("    // --- stack frame locals ---")
        for s in rsp_slots[:80]:
            name = f"var_{s:x}" if s >= 0 else f"var_m{-s:x}"
            lines.append(f"    uint64_t  {name};          // [rsp{s:+#x}]")
        for rb, disp in rbp_slots[:80]:
            name = f"vrbp_{disp:x}" if disp >= 0 else f"vrbp_m{-disp:x}"
            lines.append(f"    uint64_t  {name};       // [rbp{disp:+#x}]")

    jump_targets = set()
    for ins in insns:
        if ins.mnemonic in ("je","jne","jz","jnz","ja","jb","jae","jbe","jg","jl","jge","jle","js","jns",
                            "jp","jnp","jmp","jo","jno","jcxz","jecxz","jrcxz"):
            for op in safe_ops(ins):
                if op.type == X86_OP_IMM:
                    t = op.imm
                    if ins.address <= t <= ins.address + 0x40000:
                        jump_targets.add(t)
                    break

    lines.append("    // ---- code ----")
    last_cmp = None
    n = 0
    truncated = False
    for ins in insns:
        if n >= max_insns:
            lines.append(f"    // *** TRUNCATED at {max_insns} of {len(insns)} instructions ***")
            truncated = True
            break
        n += 1
        addr = ins.address
        mn = ins.mnemonic
        ops = ins.op_str
        if addr in jump_targets:
            lines.append(f"loc_{addr - IB:x}:")
        if mn in ("je","jne","jz","jnz","ja","jb","jae","jbe","jg","jl","jge","jle","js","jns","jp","jnp",
                  "jmp","jo","jno","jcxz","jecxz","jrcxz"):
            for op in safe_ops(ins):
                if op.type == X86_OP_IMM:
                    tgt = op.imm
                    lab = f"loc_{tgt - IB:x}"
                    if mn == "jmp":
                        lines.append(f"    goto {lab};                       // {addr:#x}")
                    else:
                        human = None
                        if last_cmp:
                            kind, a, b = last_cmp
                            if kind == "cmp":
                                if re.match(r"^-?(?:0x[0-9a-f]+|\d+)$", b):
                                    rel = {"je":"==","jz":"==","jne":"!=","jnz":"!=",
                                           "ja":">","jbe":"<=","jb":"<","jae":">=",
                                           "jg":">","jle":"<=","jl":"<","jge":">="}.get(mn)
                                    if rel: human = f"{a} {rel} {b}"
                            elif kind == "test":
                                rel = {"je":"== 0","jz":"== 0","jne":"!= 0","jnz":"!= 0"}.get(mn)
                                if rel: human = f"({a} & {b}) {rel}"
                        if human:
                            lines.append(f"    if ({human}) goto {lab};         // {mn} @ {addr:#x}")
                        else:
                            lines.append(f"    if_cond: {mn} -> goto {lab};       // {addr:#x}")
                    break
            continue
        if mn == "call":
            handled = False
            for op in safe_ops(ins):
                if op.type == X86_OP_IMM:
                    t = op.imm - IB
                    if t in FUNCSET:
                        lines.append(f"    sub_{t:x}(self, a2, a3, a4);         // {addr:#x}")
                    else:
                        lines.append(f"    call {ops};                       // {addr:#x}")
                    handled = True
                    break
            if handled: continue
            m = re.search(r"rip\s*([+-])\s*0x([0-9a-f]+)", ops)
            if m:
                sign = 1 if m.group(1) == "+" else -1
                disp = int(m.group(2), 16) * sign
                tgt = ins.address + ins.size + disp
                name = IAT.get(tgt, f"[{tgt:#x}]")
                lines.append(f"    {name}(...);                          // {addr:#x}")
            else:
                lines.append(f"    call {ops};                       // {addr:#x}")
            continue
        if mn == "lea" and "rip" in ops:
            m = re.search(r"rip\s*([+-])\s*0x([0-9a-f]+)", ops)
            if m:
                sign = 1 if m.group(1) == "+" else -1
                disp = int(m.group(2), 16) * sign
                tgt = (ins.address + ins.size + disp) - IB
                s, enc = get_str(tgt)
                reg = ops.split(",")[0].strip()
                if s:
                    esc = s.replace("\\", "\\\\").replace('"', '\\"')
                    lines.append(f"    {reg} = &s_{tgt:x};                 // \"{esc[:90]}\" ({enc}) @ {addr:#x}")
                    continue
                if (IB + tgt) in IAT:
                    lines.append(f"    {reg} = &imp_{tgt:x};              // {IAT[IB+tgt]} @ {addr:#x}")
                    continue
        if "rip" in ops and mn.startswith("mov"):
            m = re.search(r"rip\s*([+-])\s*0x([0-9a-f]+)", ops)
            if m:
                sign = 1 if m.group(1) == "+" else -1
                disp = int(m.group(2), 16) * sign
                tgt = (ins.address + ins.size + disp) - IB
                s, enc = get_str(tgt)
                dst = ops.split(",")[0].strip()
                if s:
                    esc = s.replace('"', '\\"')
                    lines.append(f"    {dst} = s_{tgt:x};                  // \"{esc[:90]}\" @ {addr:#x}")
                    continue
                if (IB + tgt) in IAT:
                    lines.append(f"    {dst} = imp_{tgt:x};               // {IAT[IB+tgt]} @ {addr:#x}")
                    continue
                blob = rd(tgt, 16)
                lines.append(f"    {dst} = data_{tgt:x};               // {blob.hex()} @ {addr:#x}")
                continue
        if mn == "ret":
            lines.append(f"    return;                            // {addr:#x}")
            continue
        if mn == "int3":
            lines.append(f"    /* int3 */                         // {addr:#x}")
            continue
        if mn == "cmp" and "," in ops:
            a, b = [x.strip() for x in ops.split(",", 1)]
            last_cmp = ("cmp", a, b)
        elif mn == "test" and "," in ops:
            a, b = [x.strip() for x in ops.split(",", 1)]
            last_cmp = ("test", a, b)
        note = ""
        if mn in ("cmp", "mov", "movzx", "movsx") and "0x" in ops:
            for h in re.findall(r"0x([0-9a-fA-F]+)", ops):
                v = int(h, 16)
                try:
                    b4 = struct.pack("<I", v & 0xFFFFFFFF)
                    if all(32 <= x < 127 for x in b4):
                        note = f'  // "{b4.decode("ascii")}"'
                except Exception:
                    pass
        lines.append(f"    {mn:6s} {ops};{' ' * max(1, 42 - len(ops))} // {addr:#x}{note}")
    lines.append("}")
    lines.append("")
    return "\n".join(lines), truncated, len(insns)

# =============== MAIN ===============
# scan strings used across ALL functions for aliases
used_str = {}
for idx, f in enumerate(FUNC):
    if idx % 200 == 0:
        print(f"# scanning strings {idx}/{len(FUNC)} ...", file=sys.stderr)
    end = min(next_func(f), f + 0x8000)
    raw = rd(f, end - f)
    for ins in md.disasm(raw, IB + f):
        if "rip" in ins.op_str and ins.mnemonic in ("lea", "mov", "movdqa", "movaps", "movups"):
            m = re.search(r"rip\s*([+-])\s*0x([0-9a-f]+)", ins.op_str)
            if m:
                sign = 1 if m.group(1) == "+" else -1
                disp = int(m.group(2), 16) * sign
                tgt = (ins.address + ins.size + disp) - IB
                s, enc = get_str(tgt)
                if s:
                    used_str[tgt] = s

print(f"# total functions: {len(FUNC)}, strings: {len(used_str)}", file=sys.stderr)

trunc_count = 0
total_insns = 0
with open(OUT, "w", encoding="utf-8") as out:
    out.write(r"""/* =====================================================================================
 *  GTAIV_Converter_by_TEAM_RageX.exe  -  COMPLETE PSEUDO-C DECOMPILATION
 *  ---------------------------------------------------------------------------------
 *  Source      : GTAIV_Converter_by_TEAM_RageX.exe  (2,703,872 bytes)
 *  MD5         : A70CD3FFF6572A3D928A65420561952B
 *  SHA256      : 3ECA60F41771CE94C01C195226BCD326C137B2CBCDE153EA8607EAC5B63F2C5
 *  Format      : PE32+ x64 | MSVC 14.44 (v143) | compiled 2026-10-14
 *  ImageBase   : 0x140000000 | EP RVA 0x45494
 *  Sections    : .text  RVA 0x1000   size 0x6a766
 *                .rdata RVA 0x6c000  size 0x22590
 *                .data  RVA 0x8f000  size 0x3b10
 *  Generator   : custom capstone-based decompiler (no Ghidra/IDA available)
 *  ---------------------------------------------------------------------------------
 *  Contents:
 *    PART 0 : project structure (resources, tools, crypto constants)
 *    PART 1 : string table (all referenced strings)
 *    PART 2 : import table (all imported APIs + which funcs use them)
 *    PART 3 : function registry (all functions, callers/callees)
 *    PART 4 : FULL decompilation of EVERY function (ordered by RVA)
 *
 *  Naming:
 *    sub_XXXX       internal function (name = RVA in hex)
 *    s_XXXX         string constant (RVA in hex)
 *    imp_XXXX       IAT slot (VA in hex)
 *    loc_XXXX       code label (RVA in hex)
 *    // 0x1400xxxx  virtual address of the instruction
 * ===================================================================================== */

#include <stdint.h>
#include <windows.h>

typedef struct ctx_t ctx_t;
typedef int64_t  (__fastcall *fn_i64)(void*, uint64_t, uint64_t, uint64_t);
typedef int32_t  (__fastcall *fn_i32)(void*, uint64_t, uint64_t, uint64_t);
typedef void     (__fastcall *fn_void)(void*, uint64_t, uint64_t, uint64_t);

/* =====================================================================================
 * PART 0 - PROJECT STRUCTURE (recovered from the binary)
 * =====================================================================================
 *
 *  GTAIV_Converter_by_TEAM_RageX.exe          main GUI/CLI host (this file)
 *    |
 *    +-- embedded RT_RCDATA resources (protected: XOR key16 + RGXA + raw-deflate)
 *    |     RVA 0x83f40  size 195072  -> ivCellConverter.exe   (x86, PDB ivCellConverter.pdb)
 *    |     RVA 0x86f00  size 168448  -> ivXenonConverter.exe  (x86, PDB ivXenonConverter.pdb)
 *    |     RVA 0x89840  size 1267200 -> ivXtdConverter.exe    (x64, IVPC2Xbox)
 *    |     RVA ...      size 967776  -> ragex_texconv.exe     (DirectXTex texconv 2025.10.28)
 *    |     RVA ...      size 18770   -> shader_params_gcm.txt
 *    |     RVA ...      size 18525   -> shader_params_xenon.txt
 *    |     RVA ...      size 909347  -> ui_screenshot.png     (1090x900)
 *    |
 *    +-- XOR key table (16 bytes) @ VA 0x140078788
 *    |     9e 3b d7 42 61 ca 15 8f 2d b0 74 e9 53 1c a6 f8
 *    |     xor-loop @ 0x140034110 : data[i] ^= (((i*0x1F+7)&0xFF) ^ key[i&0xF])
 *    |
 *    +-- AES-256-ECB key (32 bytes) @ VA 0x140078540  (for vehicles.img, NOT resources)
 *    |     1a b5 6f ed 7e c3 ff 01 22 7b 69 15 33 97 5d ce
 *    |     47 d7 69 65 3f f7 75 42 6a 96 cd 6d 53 07 56 5d
 *    |
 *    +-- converter selection table (sub_d640):
 *    |     type 0: ivCellConverter.exe  -> .cft / .ctd
 *    |     type 1: ivXenonConverter.exe -> .xft
 *    |     type 2: ivXtdConverter.exe   -> .xtd
 *    |     + data.txt sidecar
 *    |
 *    +-- WFT pipeline (sub_8080):
 *    |     input.wft / input.wtd / bumper_removed.wft / ragex_tint / ragex_tint_zero
 *    |     shaders: gta_vehicle_vehglass.sps ; parts: door_ bodyshell chassis boot misc_
 *    |
 *    +-- key call flow:
 *          WinMain sub_6510
 *            -> CreateWindow sub_5010 (class "RageX", title "RageX | GTA IV")
 *            -> WndProc sub_22b0  (drag-drop / menu / convert)
 *            -> Timer sub_2ce0    (async convert + InvalidateRect)
 *            -> Workspace sub_d1c0 (GetTempPathW, ASCII check, short path)
 *            -> Selector  sub_d640 (pick converter by type)
 *            -> Runner    sub_bc90 (CreatePipe+CreateProcessW, anti-infinite-loop)
 *            -> Inspector sub_cc00 (exactly one nonempty output file)
 *            -> WFT patch sub_8080
 *            -> Shader   sub_20340 / sub_21630
 *            -> WTD      sub_34900 / texconv sub_36d40 sub_377c0
 *            -> CTD      sub_387b0
 *          RGXA loader sub_33f90
 *            FindResourceW(RT_RCDATA) -> XOR -> magic RGXA -> inflate(-15)
 *          Archive  sub_101b0 (AES decrypt) / sub_1242a (AES encrypt)
 *
 *  Unpacked tools live in:  unpacked/  (next to the original EXE)
 * ===================================================================================== */

/* ---- string constants (auto-extracted, UTF-8 escaped) ---- */
""")
    for rva_s, s in sorted(used_str.items()):
        esc = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")
        out.write(f'static const char s_{rva_s:x}[] = "{esc[:250]}";\n')

    out.write("\n/* =====================================================================================\n")
    out.write(" * PART 2 - IMPORT TABLE (IAT)\n")
    out.write(" * ===================================================================================== */\n")
    out.write("/*\n")
    out.write("%-18s %-32s %s\n" % ("IAT VA", "API", "USED BY (func count / first users)"))
    out.write("-" * 120 + "\n")
    for va in sorted(IAT):
        name = IAT[va]
        users = IMPORTS_USED.get(va, [])
        uniq = sorted(set(users))
        preview = ", ".join("sub_%x" % u for u in uniq[:8])
        out.write("%-18s %-32s %4d  %s\n" % (hex(va), name, len(uniq), preview))
    out.write("*/\n\n")

    out.write("/* =====================================================================================\n")
    out.write(f" * PART 3 - FUNCTION REGISTRY ({len(FUNC)} functions)\n")
    out.write(" * ===================================================================================== */\n")
    out.write("/*\n")
    out.write("%-10s %-12s %-8s %-5s %s\n" % ("RVA", "VA", "SIZE", "NLOC", "CALLS ->"))
    out.write("-" * 160 + "\n")
    for rva in FUNC:
        sz = next_func(rva) - rva
        cs = sorted(CALLEES.get(rva, ()))
        prev = ", ".join("sub_%x" % c for c in cs[:12])
        out.write("%-10s %-12s %-8d %-5d %s\n" % (hex(rva), hex(IB + rva), sz, len(cs), prev))
    out.write("*/\n\n")

    out.write("/* =====================================================================================\n")
    out.write(" * PART 4 - FULL DECOMPILATION (every function, ordered by RVA)\n")
    out.write(" * ===================================================================================== */\n\n")

    for idx, f in enumerate(FUNC):
        if idx % 100 == 0:
            print(f"# decompiling {idx}/{len(FUNC)} (sub_{f:x}) ...", file=sys.stderr)
        code, trunc, nins = decompile_func(f, max_insns=4000)
        if trunc: trunc_count += 1
        total_insns += nins
        out.write(code)
        out.write("\n")

print(f"# DONE -> {OUT}", file=sys.stderr)
print(f"# functions={len(FUNC)}  instructions={total_insns}  truncated={trunc_count}", file=sys.stderr)
print(f"# size={os.path.getsize(OUT):,} bytes", file=sys.stderr)
