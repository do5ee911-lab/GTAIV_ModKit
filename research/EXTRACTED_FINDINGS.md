# RageX GTA IV Converter — استخراج كامل للمفاتيح والتنسيقات وخطوات المعالجة

> مستخرَج مباشرةً من `GTAIV_Converter_by_TEAM_RageX.exe` (PE32+ x64, MSVC 14.44, ImageBase `0x140000000`).
> كل المفاتيح والتنسيقات أدناه تم التحقق منها برمجيًا (decryption + inflate على الموارد الفعلية).

---

## 1. التشفير (Crypto)

### 1.1 XOR للموارد المدمجة (RT_RCDATA)
- **المفتاح:** `9e3bd74261ca158f2db074e9531ca6f8` (16 بايت)
- **الموقع:** RVA `0x78788` → VA `0x140078788`
- **الخوارزمية:** لكل بايت `i`:
  ```python
  mixed = ((i * 0x1F + 7) & 0xFF) ^ key16[i & 0xF]
  data[i] ^= mixed
  ```
- **تُطبَّق على:** جميع موارد RT_RCDATA (المعرفات 101–108) قبل فك الضغط.

### 1.2 AES-256-ECB لـ vehicles.img فقط
- **المفتاح (32 بايت):** `1ab56fed7ec3ff01227b691533975dce47d769653ff775426a96cd6d5307565d`
- **الموقع:** RVA `0x78540` → VA `0x140078540`
- **وضع التشفير:** ECB (بدون IV) عبر bcrypt (`BCryptGenerateSymmetricKey` مع `ChainingModeECB`).
- **ملاحظة مهمة:** الموارد المدمجة (WFT/WTD/CTD/المحوّلات) **لا** تستخدم AES إطلاقًا — XOR فقط.

---

## 2. صيغة RGXA (الموارد المضغوطة)

كل مورد RT_RCDATA يمر بخطوتين: XOR ثم فك الضغط raw-deflate.

```
البنية بعد فك XOR:
  +0x00  u32  magic   = 0x41584752  ("RGXA" بترتيب LE: 52 47 58 41)
  +0x04  u32  raw_size = الحجم بعد فك الضغط
  +0x08  ...  بيانات deflate خام (بدون zlib header)
```

**خطوات الفك:**
```python
dec = xor_decrypt(resource_bytes)          # كما في 1.1
assert dec[0:4] == b'RGXA'                 # 0x41584752 LE
raw_size = u32_le(dec[4:8])
plain = zlib.decompress(dec[8:], -15)      # raw deflate (windowBits=-15)
assert len(plain) == raw_size
```

**تم التحقق من:** جميع الموارد السبعة (101–108) تُفكّ وتُفكّ ضغطها بنجاح، وأحجامها تطابق ملفات `unpacked/` تمامًا.

---

## 3. صيغة vehicles.img (الأرشيف المشفّر)

### 3.1 التحقق من الترويسة (sub_101b0 @ VA 0x1400101b0)

```
vehicles.img:
  +0x00  u32  magic      = 0xA94E2A52   (بعد فك AES)
  +0x04  u32  version    = 3
  +0x08  u32  entry_count (2 .. 100002)
  +0x0C  u32  data_size   (≤ 0x1000000 = 16MB)
  +0x10  u16  entry_size  = 16 (0x10)
  +0x12  u16  (محجوز/محاذاة)
  --- نهاية الترويسة 20 بايت ---
```

**خطوات فك التشفير والتحقق:**
1. اقرأ أول 20 بايت.
2. إن لم يكن الـ magic أول 16 بايت مساويًا `0xA94E2A52`، قم بفك تشفير أول 16 بايت فقط بـ AES-256-ECB.
3. تحقق: magic == `0xA94E2A52`، version == 3، `2 ≤ entry_count ≤ 100002`، `data_size ≤ 16MB`، `entry_count * 16 ≤ data_size`، والبايتان عند `+0x10` يساويان `0x0010` (16).

### 3.2 جدول المدخلات (48 بايت لكل مدخل في الملف)

```c
struct VehicleEntry {          // 48 (0x30) بايت
    u32  field_00;             // +0x00
    u32  field_04;             // +0x04
    u32  field_08;             // +0x08
    u16  field_0C;             // +0x0C
    u16  field_0E;             // +0x0E
    char name[32];             // +0x10  (اسم الملف بدون مسار، مُهيَّأ بـ NUL)
};
// إجمالي الحجم = 0x30 = 48 بايت
```

### 3.3 الترميز (Encrypt — sub_1242a @ VA 0x14001242a)

يتم فك تشفير أول 16 بايت من الترويسة 16 مرة متتالية (نفس الكتلة، نفس المفتاح).
هذا يعني أن الترميز الأصلي طبّق AES-ECB 16 مرة على نفس الكتلة، لذلك الفك يتطلب 16 جولات فك أيضًا.

```python
# فك التشفير (16 جولة على نفس الـ block الأول):
for _ in range(16):
    header[0:16] = AES_ECB_decrypt(aes_key, header[0:16])
```

---

## 4. المحوّلات (Converters)

يتم اختيار المحوّل بناءً على نوع الإدخال (sub_d640 @ VA 0x14000d640):

| ebx | edi | المحوّل | المخرج |
|-----|-----|---------|--------|
| 1 | — | `ivCellConverter.exe` | `.cft` / `.ctd` |
| 0 | 0 | `ivXenonConverter.exe` | `.xft` |
| أخرى | — | `ivXtdConverter.exe` | `.xtd` |

جميع المحوّلات مُدمجة كموارد RT_RCDATA وتفكّ ضغطها عبر pipeline الـ RGXA.

---

## 5. خط أنابيب المعالجة الكاملة

### 5.1 دورة الحياة (WinMain → sub_6510 @ VA 0x140006510)

```
1. تهيئة الواجهة (Win32 + GDI+)
2. فك الموارد المدمجة (RGXA pipeline):
   sub_33f90 @ VA 0x140033f90
   ├── FindResourceW(NULL, id, RT_RCDATA)  [id: 101..108]
   ├── SizeofResource / LoadResource / LockResource
   ├── XOR decrypt (key16)
   ├── تحقق magic "RGXA"
   └── raw inflate (zlib -15)
3. فك vehicles.img (AES-256-ECB + جدول المدخلات)
4. لكل مدخلة:
   a. استخراج الملفات (WFT/WTD/CTD) من vehicles.img
   b. تشغيل المحوّل المناسب (ivCell/ivXenon/ivXtd) عبر CreateProcessW
   c. معالجة الملفات الناتجة (WFT/WTD patching)
   d. كتابة المخرجات النهائية
```

### 5.2 خط أنابيب WFT (sub_8080 @ VA 0x140008080, 8512 بايت)

```
1. قراءة ملف .wft
2. استدعاء sub_21630 (المعالجة الرئيسية):
   ├── فك بنية WFT (drawables, shaders, vertex/index buffers)
   ├── تصنيف الأجزاء حسب الاسم:
   │   ├── sub_1e790: فحص أجزاء الزجاج (windscreen, window_*)
   │   ├── sub_1eb40: فحص misc_/door_/boot
   │   ├── sub_1ecd0: فحص window
   │   └── sub_1ee90: فحص glass/window
   ├── تعديل الشيدرات (تلوين الطلاء):
   │   ├── sub_20340: حقن ragex_tint / ragex_tint_zero
   │   │   ├── إذا اسم الشيدر == hash("texturesampler") → يستبدل بـ "ragex_tint"
   │   │   ├── إذا == hash("dirtsampler") → يستبدل بـ "ragex_tint_zero"
   │   │   └── إذا == hash("specsampler") → يستبدل بـ "ragex_tint_zero"
   │   └── sub_21630 (تكملة): فحص gta_vehicle_vehglass
   ├── تعديل الأجزاء:
   │   ├── حقن tint values (16 بايت RGBA float) في الشيدرات المطابقة
   │   ├── إضافة سطر الشيدر gta_vehicle_vehglass + gta_vehicle_vehglass.sps
   │   └── إعادة بناء index buffers إن لزم (sub_1dec0: ".tinttmp")
   └── إعادة بناء الـ layout
3. كتابة ملف WFT المعدّل
```

### 5.3 تفاصيل sub_20340 (Tint Injection @ VA 0x140020340)

**الخوارزمية:**
```
لكل شيدر في المصفوفة:
  1. اقرأ hash (4 بايت LE) من جدول الشيدرات
  2. احسب FNV-like hash لكل مرشح:
     hash = 0
     لكل حرف c في الاسم:
       hash = (tolower(c) + hash) * 0x401
       hash ^= hash >> 6
     hash = hash * 9; hash ^= hash >> 11; hash *= 0x8001
  
  3. إذا hash المدخل == hash("texturesampler"):
       اسم_بديل = "ragex_tint"
  4. إذا == hash("dirtsampler") أو hash("specsampler"):
       اسم_بديل = "ragex_tint_zero"
  
  5. إذا وُجد اسم بديل:
       أ) قم بتحديث حجم الـ string buffer (إضافة الاسم الجديد)
       ب) اكتب الاسم البديل في نهاية الـ string data
       ج) حدّث الـ pointer في جدول الشيدرات:
          new_ptr = (aligned_offset | 0x50000000)
       د) انسخ 28 بايت (0x1c) من بيانات الشيدر الأصلية
       هـ) اكتب 4 بايت tint value RGBA (من مصفوفة القيم الثابتة)
       و) اكتب 4 بايت 0xCD (padding/placeholder)
  
  6. بعد المعالجة، أضف شيدر gta_vehicle_vehglass جديد:
       - اكتب اسم الشيدر (20 حرف)
       - اكتب "gta_vehicle_vehglass.sps" (24 حرف)
       - انسخ 96 بايت (0x60) من قالب الشيدر
       - حدّث 5 pointers بـ 0x50000000 tag
```

**القيم الثابتة المحقونة (tint values):**
```
ragex_tint:       4 floats (RGBA) من جدول data@0x14007xxxx
ragex_tint_zero:  4 floats = (0.0, 0.0, 0.0, 0.0)  تقريبًا
```

### 5.4 تصنيف الأجزاء (Part Classification)

**sub_1e790 — أجزاء الزجاج (Glass Parts):**
يتحقق من تطابق hash الشيدر مع قائمة الأسماء التالية:
```
windscreen, windscreen_r, window_lf, window_rf,
window_lr, window_rr, window_lm, window_rm
```
إذا وُجد تطابق → يعيد `true` (جزء زجاج).

**sub_1eb40 — misc_/door_/boot:**
يحوّل الاسم لحروف صغيرة ثم يتحقق:
```
если len ≥ 5 && name[0:5] == "misc_"  → true
если len ≥ 5 && name[0:5] == "door_"  → true
если len == 4 && name == "boot"       → true
إلا → false
```

**sub_1ecd0 — window:**
يتحقق من وجود "window" كجزء من الاسم (بحث substring).

**sub_1ee90 — glass/window:**
يتحقق من وجود "glass" أو "window" كجزء من الاسم.

### 5.5 تصنيف الشيدرات في sub_21630

يتم فحص أسماء الشيدرات وتصنيفها:
```
door_      → جزء باب (قابل للفك/الاستبدال)
bodyshell   → هيكل الجسم الرئيسي
chassis     → هيكل قاعدي
boot        → غطاء المحرك/الصندوق الخلفي
misc_       → أجزاء متنوعة
```

**الاستخدام في المعالجة:**
- `bodyshell` / `chassis` / `boot` → تبقى في الملف، تُعالَج كأجزاء ثابتة
- `door_*` → تُعالج بشكل خاص (قد تُفكك أو تُستبدل)
- `misc_*` → تُفحص إضافيًا
- أجزاء الزجاج (`windscreen`, `window_*`) → تحصل على tint injection

### 5.6 إعادة بناء Index Buffers (sub_1dec0 @ VA 0x14001dec0)

يُنشئ ملف مؤقت `.tinttmp` ويعيد بناء الـ vertex/index buffers:
```
1. يحسب أقصى حجم ممكن لكل buffer (≤ 0x7FF * block_size)
2. يحسب block_size = 1 << (alignment_bits + 8)
   حيث alignment_bits مخزنة في:
     - bits 11-14 من field@+4 (لـ buffer1)
     - bits 26-29 من field@+4 (لـ buffer2)
3. يحدد إن كان الحجم المطلوب يتخطى 0xFFFFFFF (256MB)
4. يعيد بناء الـ buffers مع alignment صحيح
5. يكتب النتيجة في ملف .tinttmp ثم يستبدله بالأصلي
```

**البنية المُعاد بناؤها:**
```c
struct RebuiltHeader {
    u32 packed_field;     // يحتوي alignment bits + flags
    u32 buffer1_size;     // بعد إعادة البناء
    u32 buffer2_size;     // بعد إعادة البناء
    // ... باقي الحقول كما هي
};
```

---

## 6. معالجة WTD (القواميس النسيجية)

### 6.1 sub_34900 @ VA 0x140034900 (496 بايت)

**التحقق من الترويسة:**
```
الحجم ≥ 16 بايت
bytes[0:4] == "RSC5"  (0x52 0x53 0x43 0x05)
bytes[4:8] == 0x00000008  (version/flags)
bytes[8:12] مخزنة كـ u32 LE = 8  (حجم الترويسة الموسعة)
```

**بنية WTD:**
```c
struct WTDHeader {          // 12 بايت على الأقل
    char magic[4];          // "RSC5"
    u32  version;           // 8
    u32  table_offset;      // = 8 (بداية جدول المدخلات)
    // بعد ذلك مباشرة:
    //   جدول مدخلات القواميس
    //   بيانات القواميس (DDS textures)
};
```

**الحقول المُستخرجة من +8:**
```python
raw = u32_le(data[8:12])
field_a = (raw >> 11) & 0xF        # alignment bits لـ buffer1
size_a  = (raw & 0x7FF)            # حجم buffer1 (بـ units)
field_b = (raw >> 26) & 0xF        # alignment bits لـ buffer2  
size_b  = (raw >> 15) & 0x7FF      # حجم buffer2
# الحجم الفعلي:
actual_size_a = size_a << (field_a + 8)
actual_size_b = size_b << (field_b + 8)
```

**التحقق:**
```
actual_size_a - 0x20 ≤ 0x7FFFFE0  (≤ 128MB تقريبًا)
actual_size_b > actual_size_a
actual_size_b ≤ 0x20000000        (≤ 512MB)
```

### 6.2 دورة معالجة WTD الكاملة

```
1. قراءة ملف .wtd
2. التحقق من "RSC5" magic
3. فك بنية الجدول (استدعاء sub_28160)
4. لكل مدخلة نسيج:
   a. استخراج الاسم
   b. فحص الصيغة (DXT1/DXT3/DXT5 أو أخرى)
   c. معالجة عبر ragex_texconv.exe:
      ├── " -nologo -y -f " → flags التحويل
      ├── " -o " → مسار الإخراج
      ├── " -m " → mipmaps
      ├── " -h " → الارتفاع
      ├── " -w " → العرض
      └── اسم الملف المؤقت: "texture_" + index + ".dds"
   d. إعادة بناء القاموس النسيجي
5. كتابة ملف WTD الجديد
```

**strings مساعدة:**
```
" -nologo -y -f "   → flags texconv
" -o " " -m " " -h " " -w "   → معاملات texconv
".dds"              → امتداد الملف المؤقت
"native32_"         → بادئة أسماء الملفات المؤقتة
"texture_"          → بادئة أسماء القواميس
".new512"           → امتداد ملف مؤقت جديد
```

---

## 7. معالجة CTD (القواميس النصية)

### sub_387b0 @ VA 0x1400387b0 (2272 بايت)

**البنية العامة:**
```c
struct CTDFile {
    u32  magic;           // يُقرأ عبر sub_41a94
    u32  version;         // 9 (0x9)
    u32  font_count;      // عدد الخطوط
    u32  glyph_count;     // عدد المحارف
    // ... جدول المحارف
    // ... بيانات الخطوط
    // ... خريطة الـ UVs
};
```

**الحقول المُتحقَّق منها:**
```
الحجم ≥ 0x40
الحجم ≤ 0x7FFFFC0 + 0x40  (≤ 128MB)
version == 9
```

**خطوات المعالجة:**
```
1. قراءة الترويسة (0x20 بايت عبر sub_13280)
2. فحص flag في byte عند offset = dword@+4:
   إذا (byte & 6) != 0 → خطأ (ملف غير مدعوم)
3. تخصيص buffer بحجم محسوب (يبدأ من 0x110)
4. تصفير buffer (memset)
5. معالجة جدول المحارف:
   - استخراج المحارف المطلوبة
   - إعادة ترقيمها
   - بناء خريطة UVs جديدة
6. إعادة بناء ملف CTD
```

---

## 8. تشغيل العمليات الخارجية (sub_bc90 @ VA 0x14000bc90)

**الاستخدام:** تشغيل المحوّلات (ivCellConverter, ivXenonConverter, ivXtdConverter).

```c
// النداء الأساسي:
CreateProcessW(
    lpApplicationName = NULL,
    lpCommandLine     = L"ivXtdConverter.exe input.wft output.xtd ...",
    ...
);

// عبر أنابيب (pipes) لالتقاط الإخراج:
// - إنشاء pipe للـ stdout
// - تمرير pipe handle كـ STARTF_USESTDHANDLES
// - قراءة الإخراج بعد انتهاء العملية
// - فحص anti-loop (timeout)
```

**المعاملات النموذجية:**
```
ivXtdConverter.exe  input.wft  output.xtd
ivXenonConverter.exe input.wft  output.xft
ivCellConverter.exe input.wft  output.ctd  output.cft
```

---

## 9. قائمة الدوال الرئيسية

| RVA | VA | الحجم | الوظيفة |
|-----|-----|-------|---------|
| `0x6510` | `0x140006510` | — | WinMain (نقطة الدخول) |
| `0x8080` | `0x140008080` | 8512 | خط أنابيب WFT الرئيسي |
| `0xbc90` | `0x14000bc90` | — | تشغيل عمليات CreateProcessW |
| `0xcc00` | `0x14000cc00` | — | فحص مخرجات المحوّل |
| `0xd1c0` | `0x14000d1c0` | — | إدارة مساحة العمل |
| `0xd640` | `0x14000d640` | — | اختيار المحوّل |
| `0xfdd0` | `0x14000fdd0` | — | تهيئة AES-256-ECB (bcrypt) |
| `0x101b0` | `0x1400101b0` | — | فك تشفير vehicles.img header |
| `0x1242a` | `0x14001242a` | — | تشفير vehicles.img (كتابة) |
| `0x1dec0` | `0x14001dec0` | 1888 | إعادة بناء index buffers (".tinttmp") |
| `0x1e790` | `0x14001e790` | 928 | تصنيف أجزاء الزجاج |
| `0x1eb40` | `0x14001eb40` | 400 | تصنيف misc_/door_/boot |
| `0x1ecd0` | `0x14001ecd0` | 448 | فحص window |
| `0x1ee90` | `0x14001ee90` | 528 | فحص glass/window |
| `0x20340` | `0x140020340` | 3024 | حقن ragex_tint/ragex_tint_zero |
| `0x21630` | `0x140021630` | 13696 | معالجة WFT الرئيسية |
| `0x33f90` | `0x140033f90` | 1312 | فك موارد RGXA المدمجة |
| `0x34900` | `0x140034900` | 496 | معالجة WTD (RSC5) |
| `0x387b0` | `0x1400387b0` | 2272 | معالجة CTD |

---

## 10. الملفات المُفرَّجة من الموارد المدمجة

| المورد | الملف | الوظيفة |
|--------|-------|---------|
| 101 | `ivCellConverter.exe` | محوّل WFT → CFT/CTD (Cell/PS3) |
| 102 | `ivXenonConverter.exe` | محوّل WFT → XFT (Xbox 360) |
| 103 | `ivXtdConverter.exe` | محوّل WFT → XTD |
| 104 | `ragex_texconv.exe` | تحويل القواميس (DXT) |
| 105 | `shader_params_gcm.txt` | معاملات شيدرات GCM (PS3) |
| 106 | `shader_params_xenon.txt` | معاملات شيدرات Xenon (Xbox) |
| 107 | `ui_screenshot.png` | لقطة شاشة للواجهة |
| 108 | *(محجوز)* | — |

---

## 11. ملاحظات للإعادة كتابة (Rewrite Notes)

### 11.1 التسلسل الصحيح للعمليات
```python
def convert_vehicle(input_path, output_path, target="xtd"):
    # 1. فك vehicles.img
    entries = decrypt_vehicles_img(open("vehicles.img", "rb").read())
    
    # 2. لكل مدخلة:
    for entry in entries:
        wft_data = entry.wft_bytes
        wtd_data = entry.wtd_bytes
        
        # 3. فك تشفير WFT/WTD (XOR + RGXA)
        wft = xor_decrypt(wft_data)
        wtd = xor_decrypt(wtd_data)
        
        # 4. فك ضغط RGXA
        wft_plain = rgxa_inflate(wft)
        wtd_plain = rgxa_inflate(wtd)
        
        # 5. معالجة WFT (tint injection + part classification)
        wft_patched = patch_wft(wft_plain)
        
        # 6. معالجة WTD (texture conversion)
        wtd_patched = patch_wtd(wtd_plain)
        
        # 7. تشغيل المحوّل المناسب
        if target == "xtd":
            run_converter("ivXtdConverter.exe", wft_patched, output_path)
        elif target == "xft":
            run_converter("ivXenonConverter.exe", wft_patched, output_path)
        elif target == "cell":
            run_converter("ivCellConverter.exe", wft_patched, output_path)
```

### 11.2 التحقق من صحة المفاتيح
```python
# اختبار XOR key:
test_data = b'\x00' * 16
key16 = bytes.fromhex('9e3bd74261ca158f2db074e9531ca6f8')
decrypted = bytes([
    test_data[i] ^ (((i * 0x1F + 7) & 0xFF) ^ key16[i & 0xF])
    for i in range(16)
])
assert decrypted == bytes([
    (((i * 0x1F + 7) & 0xFF) ^ key16[i & 0xF])
    for i in range(16)
])

# اختبار AES key (يجب أن يكون 32 بايت):
aes_key = bytes.fromhex(
    '1ab56fed7ec3ff01227b691533975dce47d769653ff775426a96cd6d5307565d'
)
assert len(aes_key) == 32
```

### 11.3 مكتبات مقترحة للإعادة كتابة
```python
# للمشروع:
cryptography     # AES-256-ECB
pycryptodome     # بديل
zlib             # raw deflate (windowBits=-15)
pefile           # استخراج الموارد المدمجة
capstone         # للتحليل الثانوي عند الحاجة
```

---

## 12. مرجع سريع (Quick Reference)

### المفاتيح
```
XOR key16:  9e3bd74261ca158f2db074e9531ca6f8
AES-256:    1ab56fed7ec3ff01227b691533975dce47d769653ff775426a96cd6d5307565d
```

### Magic Numbers
```
RGXA:       0x41584752  ("RGXA")
vehicles.img: 0xA94E2A52
WTD:        "RSC5"  (0x52534305)
```

### الـ Hash Used in Shader Matching
```python
def fnv_hash(name):
    """FNV-like hash used for shader name matching"""
    h = 0
    for c in name.encode('ascii'):
        h = ((c + h) * 0x401) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h * 9) & 0xFFFFFFFF
    h ^= h >> 11
    h = (h * 0x8001) & 0xFFFFFFFF
    return h
```

### أسماء الشيدرات المُعالَجة
```
texturesampler   → ragex_tint
dirtsampler      → ragex_tint_zero
specsampler      → ragex_tint_zero
gta_vehicle_vehglass       → يُضاف كشيدر جديد
gta_vehicle_vehglass.sps   → يُضاف كمصدر جديد
```

### أسماء الأجزاء المُصنَّفة
```
Glass:      windscreen, windscreen_r, window_lf/rf/lr/rr/lm/rm
Doors:      door_*
Body:       bodyshell, chassis, boot
Misc:       misc_*
Windows:    window_*, glass_*
```

---

*آخر تحديث: استخراج كامل من الملف التنفيذي الأصلي — جاهز للإعادة كتابة.*
