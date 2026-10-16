import json
m = json.load(open(r"C:\Users\_MO\Desktop\14\code_map.json", encoding="utf-8"))
keys = ["RGXA","ivCell","ivXenon","ivXtd","texconv","vehicles.img","IMG3","RSC5","input.wft","bumper",
        "Converter did","CreateProcess","FindResource","BCrypt","inflate","RageX |","wft","WTD","CTD",
        "shader","GdipCreate","MessageBox","GetMessage","RegisterClass","RSC7","GetTemp","data.txt",
        "zlib","Convert","WFT","Natural8","a94e"]
hits = {}
for fs, items in m["str_by_func"].items():
    joined = " | ".join(s for _, s in items)
    for k in keys:
        if k.lower() in joined.lower():
            hits.setdefault(int(fs), set()).add(k)

for fs, ks in sorted(hits.items()):
    print(f"func @{fs:#x} keys={sorted(ks)}")
    strs = [s for _, s in m["str_by_func"].get(str(fs), [])][:8]
    for s in strs:
        print(f"    str: {s[:100]}")
    iat = [s for _, s in m["iat_by_func"].get(str(fs), [])][:12]
    if iat:
        print(f"    iat: {iat}")
    print()
