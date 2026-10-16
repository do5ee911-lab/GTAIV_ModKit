# خطة إعادة بناء احترافية — RageX GTA IV Arabic Vehicle Converter

> مبنية بالكامل على تفكيك الملف `GTAIV_Converter_by_TEAM_RageX.exe` (PE32+ x64، MSVC 14.44، إصدار 1.3.2)
> ومخرجات التفكيك: `DECOMPRESSED_CODE.c` (48088 سطر، 265 دالة مفككة + سجل 1269 دالة) و`code_map.json`.

---

## 1) ما الذي يفعله البرنامج فعليًا (مُستخرج من الكود)

### 1.1 دورة التشغيل (WinMain @ 0x140006510)
1. قراءة سطر الأوامر (`GetCommandLineW` → `CommandLineToArgvW`)؛ إن كان هناك argv → وضع CLI (يمر على `sub_22b0` للتحقق).
2. ضبط إدراك الـ DPI ديناميكيًا (`SetProcessDpiAwarenessContext` عبر `GetProcAddress`، مع fallback إلى `SetProcessDPIAware`).
3. تسجيل صنف النافذة `RageX` + إنشاء نافذة `RageX | GTA IV` بواجهة GDI+ (دالة `sub_5010`: نمط Segoe UI، LISTBOX، `DwmSetWindowAttribute` لزوايا مدوّرة/ظل).
4. حلقة رسائل قياسية (`GetMessageW`/`TranslateMessage`/`DispatchMessageW`).

### 1.2 مُحمّل الموارد المضمّنة (RGXA @ 0x140033f90)
- `FindResourceW(NULL, id, RT_RCDATA)` → `SizeofResource` → `LoadResource` → `LockResource`.
- فك تشفير الطبقة الأولى: XOR بمفتاح 16 بايتًا (`9e3bd74261ca158f2db074e9531ca6f8` @ 0x140078788) مع مؤشر `(((i*0x1F+7)&0xFF) ^ key[i&0xF])`.
- تحقق من الرمز `RGXA` + حجم مفكوك (u32 LE) ثم ضغط raw-deflate (`inflateInit2(-15)`) — دالة `sub_28540`/`sub_3d1f0`/`sub_3d4b0`.
- رسائل خطأ واضحة: `Missing embedded resource`, `Corrupt embedded resource`, `Decompressor init failed`, `Bad embedded resource size`.
- ناتج التفكيك (7 عناصر، موجودة في `unpacked/`):
  | المورد | الدور |
  |---|---|
  | `ivCellConverter.exe` (x86) | تحويل WFT/CTD — يولّد `.cft`/`.ctd` |
  | `ivXenonConverter.exe` (x86) | تحويل — يولّد `.xft` |
  | `ivXtdConverter.exe` (x64، IVPC2Xbox) | تحويل — يولّد `.xtd` |
  | `ragex_texconv.exe` (DirectXTex) | تحويل DDS/صور |
  | `shader_params_*.txt` | معاملات الشيدرات |
  | `ui_screenshot.png` | لقطة الواجهة |

### 1.3 خط التحويل (WFT pipeline @ 0x140008080)
- يبني مسارات `input.wft` / `input.wtd` داخل مساحة عمل مؤقتة، ثم `bumper_removed.wft`، وحقول `ragex_tint`.
- إدارة مساحة العمل (`sub_d1c0`): `GetTempPathW` → رفض المسارات غير ASCII → `GetShortPathNameW` → `GetTempFileNameW` → `CreateDirectoryW` (رسالة: `Temporary directory contains non-ASCII characters...`).
- اختيار المحوّل حسب نوع الإدخال (`sub_d640`): 
  - `ivCellConverter.exe` → `.cft`/`.ctd`
  - `ivXenonConverter.exe` → `.xft`
  - `ivXtdConverter.exe` → `.xtd`
  - ثم كتابة/قراءة `data.txt`.
- التنفيذ عبر أنبوبين وحلقة انتظار (`sub_bc90`): `CreatePipe` ×2 → `SetHandleInformation` → `CreateProcessW` → قراءة stdout/stderr → كشف `infinite loop` / `Unexpected wait failure` / رسالة رابط VC++ runtime.
- فحص الناتج (`sub_cc00`): `Converter created no nonempty *.file` / `Converter created multiple *.files; refusing to guess`.
- تحويل الخامات (`sub_36d40` + `sub_377c0`): تجهيز `.dds` ثم تنفيذ `ragex_texconv.exe` مع `MoveFileExW`.
- تعديل الشيدرات/الأسماء (`sub_20340`, `sub_21630`): حقن `ragex_tint`/`ragex_tint_zero`، معالجة `gta_vehicle_vehglass.sps`، تسميات الأجزاء `door_`, `bodyshell`, `chassis`, `boot`, `misc_`.
- معالجة WTD (`sub_34900`) وCTD (`sub_387b0`).

### 1.4 طبقة التشفيل (/archive)
- تحميل ملفات صور المركبات المشفّرة: AES-256-ECB عبر bcrypt (`BCryptOpenAlgorithmProvider` + `BCryptGenerateSymmetricKey` + `BCryptDecrypt`)، مفتاح 32 بايتًا @ 0x140078540، دالة `sub_101b0`، تحقق `0xa94e2a52`، جدول مدخلات 16 بايت/إدخال.
- الحفظ/التحويل: `sub_1242a` يستخدم `BCryptEncrypt` + `MoveFileExW` (مسار الكتابة الآمن).
- ملاحظة: هذا المسار يستخدم لـ `vehicles.img` على القرص — ليس للموارد المضمّنة (المضمّنة تستخدم XOR+RGXA فقط).

### 1.5 واجهة المستخدم (WndProc @ 0x1400022b0 + Timer @ 0x140002ce0)
- عناوين `RageX | GTA IV`، رسائل `MessageBoxW` للأخطاء، `GetModuleFileNameW` لمسار التشغيل.
- مؤقّت `SetTimer` + `InvalidateRect` = تنفيذ التحويل غير المتزامن ورسم تقدّمه.

---

## 2) بنية إعادة البناء المقترحة (Rewrite Architecture)

### 2.1 الاختيار التقني (موصى به)
| المكوّن | الاختيار | البديل |
|---|---|---|
| اللغة | **C++20 (MSVC v143, x64 + x86)** — متوافق 100% مع أدوات الأصل | Rust (إذا أردنا صلابة ذاكرة) |
| الواجهة | **Win32 + Direct2D/DirectWrite** (الأصل GDI+ صُنع يدويًا) | Dear ImGui لسرعة التطوير، أو Qt |
| الضغط | zlib-ng أو miniz (نفس عرض -15) | zstd مع بقاء توافق RGXA |
| التشفير | bcrypt (نفس الـ API) أو libsodium | — |
| البناء | CMake + vcpkg | MSBuild |
| التغليف | ZIP-sfx أو MSIX + إعدادات | — |

### 2.2 طبقات البرنامج
```
┌─────────────────────────────────────────────────────┐
│  app/        WinMain, WndProc, UI (Arabic RTL),     │
│              Command-line mode                      │
├─────────────────────────────────────────────────────┤
│  pipeline/   Workspace (temp dir, ASCII-safe),      │
│              ConverterSelector, ProcessRunner,      │
│              OutputInspector, TextureConv           │
├─────────────────────────────────────────────────────┤
│  format/     WFT / WTD / CTD / XTD patchers,        │
│              ShaderPatcher (ragex_tint, vehglass)   │
├─────────────────────────────────────────────────────┤
│  archive/    RGXA loader (XOR+deflate),             │
│              ImgArchive (AES-ECB, entry table)      │
├─────────────────────────────────────────────────────┤
│  core/       strings(utf16), errors(Result<T>),     │
│              logging, RAII handles, fs helpers      │
└─────────────────────────────────────────────────────┘
```

### 2.3 الوحدات ووظائفها (مطابقة لعناوين الأصل)
1. **core/raii.h** — `UniqueHandle`, `ScopedTempDir`, `WinErr::last()` (يطابق رسائل `GetLastError: ` في الأصل).
2. **core/strings** — نصوص UTF-16/UTF-8، تحقق ASCII لـ TEMP، `GetShortPathNameW` fallback.
3. **archive/rgxa.cpp** — `load_rgxa(id) → vector<uint8_t>`: FindResource → XOR(key16) → magic RGXA → inflate(-15) → sanity `uncompressed size`.
4. **archive/img_archive.cpp** — جدول المدخلات + AES-256-ECB decrypt/encrypt للترويسة (16 جولة ECB كما في `sub_101b0`/`sub_1242a`).
5. **pipeline/workspace.cpp** — إنشاء مساحة عمل آمنة مع دعم المسارات غير ASCII (الحل الأصلي: رفض + رسالة؛ نضيف: مسار قصير/وضع long-path).
6. **pipeline/process_runner.cpp** — `run(exe, args, stdin_data) → {exit_code, stdout, stderr}` مع timeout وanti-infinite-loop.
7. **pipeline/selector.cpp** — اختيار المحوّل حسب الامتداد (نفس جدول `sub_d640`).
8. **pipeline/texture_conv.cpp** — تغليف `ragex_texconv.exe`.
9. **format/patch_wft.cpp** — إزالة البومبر + tint (يطابق `bumper_removed.wft`, `ragex_tint`).
10. **format/patch_shaders.cpp** — حقن `ragex_tint`/`ragex_tint_zero` + استبدال `gta_vehicle_vehglass.sps`.
11. **format/patch_wtd.cpp / patch_ctd.cpp** — معالجة الخامات/CTD.
12. **app/ui_*** — نافذة RTL عربية، قائمة/تقطيع، سجلّ مباشر، شريط تقدّم (SetTimer + InvalidateRect).

### 2.4 التوافق الخلفي (Contracts)
- الامتدادات الناتجة: `.cft/.ctd` (Cell)، `.xft` (Xenon)، `.xtd` (PC→Xbox) — **لا تتغير**.
- الأدوات المضمّنة: **تُستخدم كما هي** (نفس الملفات في `unpacked/`) — لا إعادة تنفيذ للمحوّلات، فقط تغليفها بشكل نظيف.
- `vehicles.img` المشفّر: نفس المفتاح ونفس تخطيط جدول المدخلات.
- رسائل الخطأ: تُعاد نفس النصوص (المستخدمون عرب ويعتمدون عليها) مع إضافة ترجمة.

---

## 3) مراحل التنفيذ

### المرحلة 0 — التأسيس (1–2 يوم)
- [ ] مخزن git + CMake + vcpkg + clang-format + CI (Build ×2 معمارية).
- [ ] استيراد `unpacked/` كموارد build (embed أو install рядом بالـ exe).
- [ ] اختبار هوية: تحقق من أن XOR+inflate يستعيد كل 7 موارد (known-answer tests من `unpacked/`).

### المرحلة 1 — النواة (3–5 أيام)
- [ ] core: RAII، أخطاء، سجلّ، نصوص.
- [ ] `rgxa.cpp` + اختبارات مع بيانات فعلية.
- [ ] `workspace.cpp` + `process_runner.cpp` (timeout، anti-loop، التقاط stdout).

### المرحلة 2 — خط التحويل (5–7 أيام)
- [ ] `selector.cpp` + دعم CLI: `converter.exe convert input.wft --target cell|xenon|xtd`.
- [ ] `texture_conv.cpp` + `output_inspector` (تحقق: ملف واحد غير فارغ، لا تعدد).
- [ ] اختبارات end-to-end على عينات WFT.

### المرحلة 3 — تنسيقات الملفات (5–8 أيام)
- [ ] تفكيك تخطيط WFT/WTD/CTD/XTD من الكود المفكّك (`sub_8080`, `sub_20340`, `sub_21630`, `sub_34900`, `sub_387b0`) — هنا يبدأ عمل Ghidra/IDA حقيقي لاستخراج بنى البيانات.
- [ ] `patch_wft` (boomer removal + tint) و`patch_shaders` (infusion).
- [ ] ملفات مرجعية: هولدينغ `input.wft` ↔ `bumper_removed.wft` للمقارنة.

### المرحلة 4 — الأرشيف المشفّر (3–4 أيام)
- [ ] `img_archive.cpp` مع تحديد دقيق لتدوير ECB (يجب حلّل مفتاح الـ header الفعلي؛ محاولة AES قديمة فشلت — الاحتمال: هيدر 20 بايت + 16 جولة على نفس بلوك، أو كشف الـ IV داخل جدول المدخلات).
- [ ] اختبار قراءة/كتابة `vehicles.img`.

### المرحلة 5 — الواجهة (5–7 أيام)
- [ ] نافذة عربية RTL (`WS_EX_LAYOUTRTL`)، سحب وإفلات، سجلّ مباشر، تقدّم.
- [ ] مطابقة شكل الأصلي (من `ui_screenshot.png`: 1090×900) مع تحسين: Dark mode، إعدادات، آخر الملفات.

### المرحلة 6 — التقوية والإصدار (3–5 أيام)
- [ ] فحوصات: `/analyze`, ASan، fuzzing ل المحللات.
- [ ] تجميع الأدوات المضمّنة، إخفاء الموارد بنفس منطق RGXA أو وضع أبسط (UPX-less pack).
- [ ] توثيق، مثبّت، إصدار 2.0.0 مع سجل تغييرات.

**إجمالي تقديري: 4–6 أسابيع لشخص واحد.**

---

## 4) مخاطر معروفة وحلولها
| الخطر | التأثير | الحل |
|---|---|---|
| مخطط AES لـ `vehicles.img` غير مكتمل (محاولة قديمة فشلت) | قراءة/كتابة الصور المشفّرة | تتبّع `sub_101b0`/`sub_1242a` تعليمًا بتعليم مع bcrypt real API أو تثبيت تتبّع bcrypt-by-exports |
| تحويل الشيدرات حساس للترتيب | كسر إضاءة/زجاج | اختبارات مقارنة خرج (hex diff) قبل/بعد |
| أدوات x86 على Windows x64 | فشل CreateProcess | التأكد من وجود WoW64 أو جدولة نقلها لـ x64 |
| نصوص عربية غير ASCII في مسارات المستخدم | فشل TEMP | قبول UTF-16 كاملًا (التحسين الوحيد عن الأصل) |
| حقوق أدوات الطرف الثالث (DirectXTex إلخ.) | توزيع | راجع تراخيص MIT/BSD قبل إعادة التوزيع |

---

## 5) أصول التفكيك المتاحة
- `DECOMPRESSED_CODE.c` — 48088 سطر: 265 دالة كاملة (نصوص + IAT + شروط مقروءة) + سجل 1269 دالة.
- `code_map.json` — خريطة: دالة ← نصوصها + استيراداتها.
- `decomp_map.py` / `decompile.py` — أدوات التفكيك (قابلة للتشغيل من جديد على أي دالة).
- `unpacked/` — الأدوات والمورادات السبعة المستخرجة.
