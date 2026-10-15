import json
import os
import shutil
import sys
import traceback

from PySide6 import QtCore, QtGui, QtWidgets

from . import aes
from . import cars as carsmod
from . import img as imgmod
from . import manifest as manifestmod
from . import rebuild as rebuildmod
from . import rpf as rpfmod
from . import rsc as rscmod
from . import wft as wftmod
from . import wtd as wtdmod

APP_NAME = "GTAIV Mod Kit"
DEFAULT_GAME = r"C:\Users\_MO\Desktop\13\PS3_GAME\USRDIR"
LTR = "‎"

NAVY = "#141c33"
NAVY_DARK = "#0f1526"
PANEL = "#1b2542"
PANEL_HI = "#243156"
BORDER = "#2c3a63"
GOLD = "#d4af37"
GOLD_HI = "#f0d878"
TEXT = "#e8eaf0"
MUTED = "#9aa7c7"
DANGER = "#e05c5c"
OK = "#5cd48a"

QSS = """
QMainWindow, QWidget#root { background: %(navy)s; color: %(text)s; font-family: 'Segoe UI'; font-size: 13px; }
QFrame#sidebar { background: %(dark)s; border-left: 1px solid %(border)s; }
QLabel#title { font-size: 20px; font-weight: 700; color: %(gold)s; }
QLabel#subtitle { color: %(muted)s; font-size: 12px; }
QLabel#card { background: %(panel)s; border: 1px solid %(border)s; border-radius: 10px; padding: 12px; }
QLabel#stat { color: %(gold)s; font-size: 15px; font-weight: 600; }
QPushButton { background: %(panel)s; border: 1px solid %(border)s; border-radius: 6px; padding: 7px 14px; color: %(text)s; }
QPushButton:hover { background: %(panel_hi)s; border-color: %(gold)s; }
QPushButton:pressed { background: %(dark)s; }
QPushButton#primary { background: %(gold)s; color: #101010; font-weight: 700; border: none; }
QPushButton#primary:hover { background: %(gold_hi)s; }
QPushButton#danger { border-color: %(danger)s; color: %(danger)s; }
QPushButton#nav { text-align: right; border: none; border-radius: 0; padding: 13px 16px; background: transparent; font-size: 14px; }
QPushButton#nav:hover { background: %(panel)s; }
QPushButton#nav:checked { background: %(panel)s; color: %(gold)s; border-right: 3px solid %(gold)s; font-weight: 700; }
QTableWidget { background: %(dark)s; gridline-color: %(border)s; alternate-background-color: #16203a; border: 1px solid %(border)s; border-radius: 6px; }
QHeaderView::section { background: %(panel)s; color: %(gold)s; border: none; padding: 7px; font-weight: 600; }
QTableWidget::item:selected { background: %(panel_hi)s; color: %(text)s; }
QLineEdit, QComboBox, QPlainTextEdit { background: %(dark)s; border: 1px solid %(border)s; border-radius: 5px; padding: 6px 8px; selection-background-color: %(panel_hi)s; }
QLineEdit:focus { border-color: %(gold)s; }
QStatusBar { background: %(dark)s; color: %(muted)s; border-top: 1px solid %(border)s; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QProgressDialog { background: %(panel)s; }
QScrollBar:vertical { background: %(dark)s; width: 10px; }
QScrollBar::handle:vertical { background: %(border)s; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
""" % {"navy": NAVY, "dark": NAVY_DARK, "panel": PANEL, "panel_hi": PANEL_HI,
       "border": BORDER, "gold": GOLD, "gold_hi": GOLD_HI, "text": TEXT,
       "muted": MUTED, "danger": DANGER}


def ltr(text):
    return LTR + text + LTR


def fmt_size(n):
    if n >= 1024 * 1024:
        return "%.1f MB" % (n / (1024.0 * 1024))
    if n >= 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%d B" % n


def run_async(parent, fn, on_ok, on_err=None, busy="جارٍ التنفيذ..."):
    dlg = QtWidgets.QProgressDialog(busy, None, 0, 0, parent)
    dlg.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setValue(0)
    dlg.show()
    result = {}

    class Runner(QtCore.QThread):
        def run(self):
            try:
                result["v"] = fn()
            except Exception as exc:
                result["e"] = exc
                result["tb"] = traceback.format_exc()

    thread = Runner(parent)

    def finished():
        dlg.close()
        if "e" in result:
            if on_err:
                on_err(result["e"])
            else:
                QtWidgets.QMessageBox.critical(
                    parent, "خطأ", str(result["e"]))
        else:
            on_ok(result["v"])
        try:
            parent._threads.remove(thread)
        except (ValueError, AttributeError):
            pass

    thread.finished.connect(finished)
    if not hasattr(parent, "_threads"):
        parent._threads = []
    parent._threads.append(thread)
    thread.start()
    return thread


def detect_archive(path):
    with open(path, "rb") as fh:
        head = fh.read(4)
    if head in (b"RPF2", b"RPF3"):
        return "rpf"
    try:
        imgmod.ImgArchive(path)
        return "img"
    except imgmod.ImgError:
        pass
    raise ValueError("نوع ملف غير معروف: %s" % path)


def open_any_archive(path):
    with open(path, "rb") as fh:
        head = fh.read(4)
    if head in (b"RPF2", b"RPF3"):
        return rpfmod.RpfArchive(path)
    try:
        return imgmod.ImgArchive(path)
    except imgmod.ImgError as exc:
        raise ValueError("الملف ليس أرشيف RPF أو IMG3: %s" % exc)


class Sidebar(QtWidgets.QWidget):
    def __init__(self, entries, on_nav):
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(210)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 18, 0, 18)
        lay.setSpacing(2)
        brand = QtWidgets.QLabel("  GTA IV")
        brand.setStyleSheet("color: %s; font-size: 22px; font-weight: 800;" % GOLD)
        brand2 = QtWidgets.QLabel("  MOD KIT")
        brand2.setStyleSheet("color: %s; font-size: 13px; letter-spacing: 3px;" % MUTED)
        lay.addWidget(brand)
        lay.addWidget(brand2)
        lay.addSpacing(18)
        self.group = QtWidgets.QButtonGroup(self)
        self.group.setExclusive(True)
        for i, (key, label) in enumerate(entries):
            btn = QtWidgets.QPushButton(label)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.setCursor(QtGui.Qt.CursorShape.PointingHandCursor)
            self.group.addButton(btn, i)
            lay.addWidget(btn)
            if i == 0:
                btn.setChecked(True)
        lay.addStretch(1)
        ver = QtWidgets.QLabel("  v1.0")
        ver.setStyleSheet("color: %s;" % MUTED)
        lay.addWidget(ver)
        self.group.idClicked.connect(on_nav)


class HomePage(QtWidgets.QWidget):
    def __init__(self, win):
        super().__init__()
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        title = QtWidgets.QLabel("الرئيسية")
        title.setObjectName("title")
        sub = QtWidgets.QLabel("حالة الأداة واللعبة — كل شيء جاهز للتعديل")
        sub.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(sub)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(14)
        card_dir = QtWidgets.QWidget()
        card_dir.setObjectName("card")
        cd = QtWidgets.QVBoxLayout(card_dir)
        cd.setSpacing(8)
        lbl = QtWidgets.QLabel("مسار اللعبة (USRDIR)")
        lbl.setObjectName("subtitle")
        self.dir_edit = QtWidgets.QLineEdit(win.game_dir)
        self.dir_edit.setLayoutDirection(QtCore.Qt.LayoutDirection.LeftToRight)
        browse = QtWidgets.QPushButton("استعراض...")
        browse.setCursor(QtGui.Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(win.pick_game_dir)
        drow = QtWidgets.QHBoxLayout()
        drow.addWidget(self.dir_edit, 1)
        drow.addWidget(browse)
        self.dir_status = QtWidgets.QLabel()
        self.dir_status.setObjectName("stat")
        cd.addWidget(lbl)
        cd.addLayout(drow)
        cd.addWidget(self.dir_status)
        card_dir.setMinimumWidth(360)

        card_key = QtWidgets.QLabel()
        card_key.setObjectName("card")
        card_key.setText(
            "<b>مفتاح AES-256</b><br>"
            "<span style='color:%s'>مُستخرج ومحقّق ✓</span><br>"
            "<span style='font-family:Consolas;font-size:11px'>%s</span>" % (OK, aes.KEY_HEX))

        row.addWidget(card_dir, 1)
        row.addWidget(card_key, 1)
        root.addLayout(row)

        actions = QtWidgets.QHBoxLayout()
        actions.setSpacing(12)
        for label, page in ((" السيارات ←", 2), (" الأرشيفات ←", 1),
                            (" التحويل ←", 3)):
            b = QtWidgets.QPushButton(label)
            b.setCursor(QtGui.Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, p=page: win.nav(p))
            actions.addWidget(b)
        root.addLayout(actions)
        root.addStretch(1)
        self.refresh()

    def refresh(self):
        d = self.dir_edit.text().strip()
        ok = os.path.isdir(d)
        self.dir_status.setText("اللعبة موجودة ✓" if ok else "المسار غير موجود ✗")
        self.dir_status.setStyleSheet("color: %s;" % (OK if ok else DANGER))


class ArchivesPage(QtWidgets.QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.arc = None
        self.path = ""
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)
        title = QtWidgets.QLabel("الأرشيفات")
        title.setObjectName("title")
        sub = QtWidgets.QLabel("تصفح واستخرج وبدّل ملفات RPF و IMG")
        sub.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(sub)

        top = QtWidgets.QHBoxLayout()
        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.setPlaceholderText("مسار ملف .rpf أو .img ...")
        self.path_edit.setLayoutDirection(QtCore.Qt.LayoutDirection.LeftToRight)
        b_open = QtWidgets.QPushButton("فتح")
        b_open.setObjectName("primary")
        b_open.clicked.connect(self.open_dialog)
        b_load = QtWidgets.QPushButton("تحميل")
        b_load.clicked.connect(self.load_path)
        top.addWidget(self.path_edit, 1)
        top.addWidget(b_open)
        top.addWidget(b_load)
        root.addLayout(top)

        self.info = QtWidgets.QLabel("لم يُفتح أرشيف بعد")
        self.info.setObjectName("subtitle")
        root.addWidget(self.info)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["الاسم", "الحجم", "النوع", "المسار"])
        self.table.horizontalHeader().setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table, 1)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(10)
        self.backup = QtWidgets.QCheckBox("نسخة احتياطية (.bak)")
        self.backup.setChecked(True)
        b_ext = QtWidgets.QPushButton("استخراج المحدد")
        b_all = QtWidgets.QPushButton("استخراج الكل")
        b_rep = QtWidgets.QPushButton("استبدال ملف")
        b_add = QtWidgets.QPushButton("إضافة ملف (IMG)")
        b_ver = QtWidgets.QPushButton("فحص السلامة")
        for b in (b_ext, b_all, b_rep, b_add, b_ver):
            b.setCursor(QtGui.Qt.CursorShape.PointingHandCursor)
        b_ext.clicked.connect(self.extract_selected)
        b_all.clicked.connect(self.extract_all)
        b_rep.clicked.connect(self.replace_file)
        b_add.clicked.connect(self.add_file)
        b_ver.clicked.connect(self.verify)
        bar.addWidget(self.backup)
        bar.addStretch(1)
        bar.addWidget(b_ver)
        bar.addWidget(b_add)
        bar.addWidget(b_rep)
        bar.addWidget(b_all)
        bar.addWidget(b_ext)
        root.addLayout(bar)

        bar2 = QtWidgets.QHBoxLayout()
        bar2.setSpacing(10)
        b_rbd = QtWidgets.QPushButton("إعادة بناء من مجلد")
        b_rst = QtWidgets.QPushButton("استعادة نسخة (.bak)")
        b_rbd.setCursor(QtGui.Qt.CursorShape.PointingHandCursor)
        b_rst.setCursor(QtGui.Qt.CursorShape.PointingHandCursor)
        b_rbd.clicked.connect(self.rebuild_from_folder)
        b_rst.clicked.connect(self.restore_backup)
        hint = QtWidgets.QLabel("استخرج الكل ← عدّل ← أعد البناء")
        hint.setObjectName("subtitle")
        bar2.addWidget(hint)
        bar2.addStretch(1)
        bar2.addWidget(b_rst)
        bar2.addWidget(b_rbd)
        root.addLayout(bar2)

    def open_dialog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "اختر أرشيفاً", self.win.game_dir,
            "Archives (*.rpf *.img);;All (*)")
        if path:
            self.path_edit.setText(path)
            self.load_path()

    def load_path(self):
        path = self.path_edit.text().strip()
        if not path or not os.path.isfile(path):
            QtWidgets.QMessageBox.warning(self, "تنبيه", "الملف غير موجود")
            return
        try:
            self.arc = open_any_archive(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "خطأ", str(exc))
            return
        self.path = path
        if isinstance(self.arc, rpfmod.RpfArchive):
            kind = getattr(self.arc, "kind", "RPF2")
            files = [(p, self.arc.get(p)) for p in self.arc.list_files()]
        else:
            kind = getattr(self.arc, "kind", "IMG3")
            files = [(e.name, e) for e in self.arc.entries]
        self.info.setText("%s — %d ملف • %s" % (
            kind, len(files), ltr(os.path.basename(path))))
        self.table.setRowCount(0)
        self.table.setRowCount(len(files))
        for i, (name, e) in enumerate(files):
            if isinstance(self.arc, rpfmod.RpfArchive):
                size = e.stored_size
                if e.is_resource:
                    typ = "موارد RSC"
                elif e.is_compressed:
                    typ = "مضغوط deflate"
                else:
                    typ = "عادي"
            else:
                size = e.stored_size
                typ = "موارد RSC" if e.is_resource else "عادي"
            for col, val in enumerate((name, fmt_size(size), typ, name)):
                item = QtWidgets.QTableWidgetItem(val)
                if col in (1, 2):
                    item.setTextAlignment(
                        int(QtCore.Qt.AlignmentFlag.AlignCenter))
                if col in (0, 3):
                    item.setText(ltr(val))
                self.table.setItem(i, col, item)
        self.win.status("تم فتح %s" % os.path.basename(path))

    def _require(self):
        if not self.arc:
            QtWidgets.QMessageBox.warning(self, "تنبيه", "افتح أرشيفاً أولاً")
            return False
        return True

    def _selected_paths(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return []
        out = []
        for r in rows:
            out.append(self.table.item(r, 3).text())
        return out

    def extract_selected(self):
        if not self._require():
            return
        paths = self._selected_paths()
        if not paths:
            QtWidgets.QMessageBox.warning(self, "تنبيه", "حدد ملفات من الجدول")
            return
        self._extract(paths)

    def extract_all(self):
        if not self._require():
            return
        if isinstance(self.arc, rpfmod.RpfArchive):
            paths = self.arc.list_files()
        else:
            paths = [e.name for e in self.arc.entries]
        self._extract(paths)

    def _extract(self, paths):
        outdir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "اختر مجلد الحفظ")
        if not outdir:
            return
        arc = self.arc

        def job():
            n = 0
            for p in paths:
                if isinstance(arc, rpfmod.RpfArchive):
                    blob = arc.read(p)
                else:
                    blob = arc.read(p)
                target = os.path.join(outdir, p.replace("/", os.sep))
                os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
                with open(target, "wb") as fh:
                    fh.write(blob)
                n += 1
            return n

        def ok(n):
            self.win.status("تم استخراج %d ملف" % n)
            QtWidgets.QMessageBox.information(
                self, "تم", "تم استخراج %d ملف بنجاح" % n)

        run_async(self, job, ok, busy="جارٍ الاستخراج...")

    def replace_file(self):
        if not self._require():
            return
        paths = self._selected_paths()
        if len(paths) != 1:
            QtWidgets.QMessageBox.warning(self, "تنبيه", "حدد ملفاً واحداً فقط")
            return
        inner = paths[0]
        src, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "اختر الملف البديل", "", "All (*)")
        if not src:
            return
        with open(src, "rb") as fh:
            blob = fh.read()
        is_res = blob[:4] in rpfmod.RSC_MAGICS
        if isinstance(self.arc, rpfmod.RpfArchive):
            e = self.arc.get(inner)
            if e.is_resource and not is_res:
                QtWidgets.QMessageBox.critical(
                    self, "خطأ", "هذا ملف موارد — يجب أن يبدأ بمفتاح RSC")
                return
            if not e.is_resource and is_res:
                QtWidgets.QMessageBox.critical(
                    self, "خطأ", "هذا ملف عادي — لا يمكن أن يبدأ بمفتاح RSC")
                return
        else:
            e = self.arc.get(inner)
            if e.is_resource != is_res:
                QtWidgets.QMessageBox.critical(
                    self, "خطأ", "نوع الملف غير متوافق (موارد/عادي)")
                return
        path, arc, blob, inner = self.path, self.arc, blob, inner
        backup = self.backup.isChecked()

        def job():
            if backup and not os.path.exists(path + ".bak"):
                shutil.copy2(path, path + ".bak")
            if isinstance(arc, rpfmod.RpfArchive):
                rpfmod.replace_files(path, {inner: blob})
            else:
                imgmod.replace_entries(path, replacements={inner: blob})
            return True

        def done(_):
            self.win.status("تم استبدال %s" % inner)
            QtWidgets.QMessageBox.information(self, "تم", "تم الاستبدال بنجاح")
            self.arc = open_any_archive(path)
            self.load_path()

        run_async(self, job, done, busy="جارٍ الاستبدال...")

    def add_file(self):
        if not self._require():
            return
        if not isinstance(self.arc, imgmod.ImgArchive):
            QtWidgets.QMessageBox.warning(
                self, "تنبيه", "الإضافة متاحة فقط في ملفات IMG")
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, "اسم الملف الجديد", "الاسم داخل الأرشيف (مثال: newtex.wtd):")
        if not ok or not name:
            return
        src, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "اختر الملف", "", "All (*)")
        if not src:
            return
        with open(src, "rb") as fh:
            blob = fh.read()
        path, backup = self.path, self.backup.isChecked()

        def job():
            if backup and not os.path.exists(path + ".bak"):
                shutil.copy2(path, path + ".bak")
            imgmod.replace_entries(path, additions={name: blob})
            return True

        def done(_):
            self.win.status("تمت إضافة %s" % name)
            QtWidgets.QMessageBox.information(self, "تم", "تمت الإضافة بنجاح")
            self.arc = open_any_archive(path)
            self.load_path()

        run_async(self, job, done, busy="جارٍ الإضافة...")

    def verify(self):
        if not self._require():
            return
        arc = self.arc

        def job():
            n = 0
            if isinstance(arc, rpfmod.RpfArchive):
                for p in arc.list_files():
                    arc.read(p)
                    n += 1
            else:
                for e in arc.entries:
                    arc.stored_bytes(e)
                    n += 1
            return n

        def ok(n):
            self.win.status("الفحص سليم — %d ملف" % n)
            QtWidgets.QMessageBox.information(
                self, "سليم", "كل الملفات سليمة (%d)" % n)

        run_async(self, job, ok, busy="جارٍ الفحص...")

    def rebuild_from_folder(self):
        if not self._require():
            return
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "اختر مجلد الملفات المستخرجة")
        if not folder:
            return
        path = self.path
        backup = self.backup.isChecked()

        def job():
            return rebuildmod.rebuild(path, folder, backup=backup)

        def done(stats):
            if not stats["written"]:
                msg = "لا توجد تغييرات — محتوى المجلد مطابق للأرشيف"
            else:
                msg = ("تمت إعادة بناء الأرشيف:\n"
                       "استبدال: %d\nجديد: %d\nبدون تغيير: %d / %d" % (
                           len(stats["changed"]), len(stats["added"]),
                           stats["unchanged"], stats["total"]))
            self.win.status("إعادة البناء مكتملة")
            QtWidgets.QMessageBox.information(self, "تم", msg)
            try:
                self.arc = open_any_archive(path)
                self.load_path()
            except Exception:
                pass

        run_async(self, job, done, busy="جارٍ إعادة البناء...")

    def restore_backup(self):
        if not self._require():
            return
        path = self.path
        bak = path + ".bak"
        if not os.path.exists(bak):
            QtWidgets.QMessageBox.warning(self, "تنبيه", "لا توجد نسخة .bak")
            return
        ans = QtWidgets.QMessageBox.question(
            self, "تأكيد",
            "استعادة الملف الأصلي من النسخة الاحتياطية؟",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No)
        if ans != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        def job():
            tmp = path + ".tmp"
            shutil.copy2(bak, tmp)
            os.replace(tmp, path)
            return True

        def done(_):
            self.win.status("تمت استعادة النسخة الاحتياطية")
            QtWidgets.QMessageBox.information(self, "تم", "تمت الاستعادة")
            try:
                self.arc = open_any_archive(path)
                self.load_path()
            except Exception:
                pass

        run_async(self, job, done, busy="جارٍ الاستعادة...")


class CarsPage(QtWidgets.QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cars = {}
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)
        title = QtWidgets.QLabel("السيارات")
        title.setObjectName("title")
        sub = QtWidgets.QLabel("استعرض وبدّل وثبّت مودات السيارات في vehicles.img")
        sub.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(sub)

        top = QtWidgets.QHBoxLayout()
        self.img_edit = QtWidgets.QLineEdit(
            os.path.join(win.game_dir, carsmod.VEHICLES_IMG.replace("/", os.sep)))
        self.img_edit.setLayoutDirection(QtCore.Qt.LayoutDirection.LeftToRight)
        b_ref = QtWidgets.QPushButton("تحديث")
        b_ref.setObjectName("primary")
        b_ref.clicked.connect(self.refresh)
        top.addWidget(self.img_edit, 1)
        top.addWidget(b_ref)
        root.addLayout(top)

        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["الطراز", "مجسم CFT", "قوام CTD"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self.on_select)
        root.addWidget(self.table, 1)

        form = QtWidgets.QGridLayout()
        form.setSpacing(10)
        self.ctd_edit = QtWidgets.QLineEdit()
        self.ctd_edit.setPlaceholderText("ملف .ctd (PS3) للقوام...")
        self.ctd_edit.setLayoutDirection(QtCore.Qt.LayoutDirection.LeftToRight)
        self.cft_edit = QtWidgets.QLineEdit()
        self.cft_edit.setPlaceholderText("ملف .cft (PS3) للمجسم...")
        self.cft_edit.setLayoutDirection(QtCore.Qt.LayoutDirection.LeftToRight)
        b_ctd = QtWidgets.QPushButton("استعراض")
        b_cft = QtWidgets.QPushButton("استعراض")
        b_ctd.clicked.connect(lambda: self.pick_into(self.ctd_edit, "*.ctd"))
        b_cft.clicked.connect(lambda: self.pick_into(self.cft_edit, "*.cft"))
        form.addWidget(QtWidgets.QLabel("القوام (.ctd):"), 0, 0)
        form.addWidget(self.ctd_edit, 0, 1)
        form.addWidget(b_ctd, 0, 2)
        form.addWidget(QtWidgets.QLabel("المجسم (.cft):"), 1, 0)
        form.addWidget(self.cft_edit, 1, 1)
        form.addWidget(b_cft, 1, 2)
        root.addLayout(form)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(10)
        self.backup = QtWidgets.QCheckBox("نسخة احتياطية (.bak)")
        self.backup.setChecked(True)
        b_ext = QtWidgets.QPushButton("استخراج الطراز")
        b_rep = QtWidgets.QPushButton("استبدال الطراز")
        b_rep.setObjectName("primary")
        b_inst = QtWidgets.QPushButton("تثبيت مجلد مودات")
        b_ext.clicked.connect(self.extract_model)
        b_rep.clicked.connect(self.replace_model)
        b_inst.clicked.connect(self.install_folder)
        bar.addWidget(self.backup)
        bar.addStretch(1)
        bar.addWidget(b_inst)
        bar.addWidget(b_ext)
        bar.addWidget(b_rep)
        root.addLayout(bar)
        self.refresh()

    def pick_into(self, edit, pat):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "اختر ملفاً", "", "Files (%s);;All (*)" % pat)
        if path:
            edit.setText(path)

    def refresh(self):
        img = self.img_edit.text().strip()
        if not os.path.isfile(img):
            self.table.setRowCount(0)
            return
        try:
            self.cars = carsmod.list_cars(img)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "خطأ", str(exc))
            return
        models = sorted(self.cars)
        self.table.setRowCount(0)
        self.table.setRowCount(len(models))
        for i, m in enumerate(models):
            parts = self.cars[m]
            vals = (m, fmt_size(parts.get("cft", 0)), fmt_size(parts.get("ctd", 0)))
            for col, val in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(val)
                if col:
                    item.setTextAlignment(
                        int(QtCore.Qt.AlignmentFlag.AlignCenter))
                else:
                    item.setText(ltr(val))
                self.table.setItem(i, col, item)
        self.win.status("عدد الطرازات: %d" % len(models))

    def model(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return None
        return self.table.item(rows[0], 0).text()

    def on_select(self):
        pass

    def extract_model(self):
        m = self.model()
        if not m:
            QtWidgets.QMessageBox.warning(self, "تنبيه", "حدد طرازاً أولاً")
            return
        outdir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "اختر مجلد الحفظ")
        if not outdir:
            return
        img = self.img_edit.text().strip()

        def job():
            return carsmod.extract_car(img, m, outdir)

        def ok(written):
            self.win.status("تم استخراج %s" % m)
            QtWidgets.QMessageBox.information(
                self, "تم", "تم استخراج: %s" % ", ".join(written))

        run_async(self, job, ok, busy="جارٍ الاستخراج...")

    def replace_model(self):
        m = self.model()
        if not m:
            QtWidgets.QMessageBox.warning(self, "تنبيه", "حدد طرازاً أولاً")
            return
        ctd = self.ctd_edit.text().strip() or None
        cft = self.cft_edit.text().strip() or None
        if not ctd and not cft:
            QtWidgets.QMessageBox.warning(
                self, "تنبيه", "اختر ملف ctd أو cft على الأقل")
            return
        img = self.img_edit.text().strip()
        backup = self.backup.isChecked()
        if not backup:
            agree = QtWidgets.QMessageBox.question(
                self, "تأكيد", "بدون نسخة احتياطية — متابعة؟")
            if agree != QtWidgets.QMessageBox.StandardButton.Yes:
                return

        def job():
            return carsmod.replace_car(img, m, ctd_path=ctd, cft_path=cft,
                                       backup=backup)

        def ok(out):
            self.win.status("تم تحديث %s" % m)
            QtWidgets.QMessageBox.information(
                self, "تم", "تم تحديث الطراز %s بنجاح" % m)
            self.refresh()

        run_async(self, job, ok, busy="جارٍ الاستبدال...")

    def install_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "اختر مجلد المودات (ctd/cft)")
        if not folder:
            return
        img = self.img_edit.text().strip()
        backup = self.backup.isChecked()

        def job():
            return carsmod.install_folder(img, folder, backup=backup)

        def ok(result):
            out, replaced, skipped = result
            msg = "تم استبدال %d ملف:\n%s" % (
                len(replaced), "\n".join(replaced[:30]))
            if len(replaced) > 30:
                msg += "\n..."
            if skipped:
                msg += "\n\nتم تجاوز %d ملف غير معروف" % len(skipped)
            self.win.status("تثبيت مجلد: %d ملف" % len(replaced))
            QtWidgets.QMessageBox.information(self, "تم", msg)
            self.refresh()

        run_async(self, job, ok, busy="جارٍ التثبيت...")


class ConvertPage(QtWidgets.QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.rsc = None
        self.textures = []
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)
        title = QtWidgets.QLabel("التحويل والمستكشف")
        title.setObjectName("title")
        sub = QtWidgets.QLabel(
            "WTD→CTD و WFT→CFT — استعراض ملفات اللعبة واستخراج الصور")
        sub.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(sub)

        top = QtWidgets.QHBoxLayout()
        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.setPlaceholderText("ملف .wtd / .wft / .ctd / .cft ...")
        self.path_edit.setLayoutDirection(QtCore.Qt.LayoutDirection.LeftToRight)
        b_open = QtWidgets.QPushButton("استعراض")
        b_open.clicked.connect(self.open_dialog)
        b_load = QtWidgets.QPushButton("تحميل")
        b_load.setObjectName("primary")
        b_load.clicked.connect(self.load_path)
        top.addWidget(self.path_edit, 1)
        top.addWidget(b_open)
        top.addWidget(b_load)
        root.addLayout(top)

        self.info = QtWidgets.QLabel("لم يُحمّل ملف بعد")
        self.info.setObjectName("card")
        self.info.setTextFormat(QtCore.Qt.TextFormat.RichText)
        root.addWidget(self.info)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["النصيرة", "الأبعاد", "الصيغة", "حجم البكسل"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table, 1)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(10)
        b_dds = QtWidgets.QPushButton("استخراج صور DDS")
        b_conv = QtWidgets.QPushButton("تحويل إلى PS3")
        b_conv.setObjectName("primary")
        b_dds.clicked.connect(self.extract_dds)
        b_conv.clicked.connect(self.convert)
        bar.addStretch(1)
        bar.addWidget(b_dds)
        bar.addWidget(b_conv)
        root.addLayout(bar)

    def open_dialog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "اختر ملف GTA IV", self.win.game_dir,
            "GTA IV Resources (*.wtd *.wft *.ctd *.cft);;All (*)")
        if path:
            self.path_edit.setText(path)
            self.load_path()

    def load_path(self):
        path = self.path_edit.text().strip()
        if not path or not os.path.isfile(path):
            QtWidgets.QMessageBox.warning(self, "تنبيه", "الملف غير موجود")
            return
        try:
            self.rsc = rscmod.RscFile.from_bytes(open(path, "rb").read(), path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "خطأ", str(exc))
            return
        try:
            self.textures = wtdmod.parse(self.rsc.decompressed,
                                         self.rsc.is_ps3, self.rsc.system_size)
        except Exception:
            self.textures = []
        plat = "PS3" if self.rsc.is_ps3 else "PC"
        plat_col = OK if self.rsc.is_ps3 else GOLD
        self.info.setText(
            "<b>المنصة:</b> <span style='color:%s'>%s</span> &nbsp;|&nbsp; "
            "<b>النوع:</b> %d &nbsp;|&nbsp; <b>System:</b> %s &nbsp;|&nbsp; "
            "<b>GPU:</b> %s &nbsp;|&nbsp; <b>الناتج:</b> %s<br>"
            "<b>النصائر:</b> %d" % (
                plat_col, plat, self.rsc.type,
                fmt_size(self.rsc.system_size), fmt_size(self.rsc.gpu_size),
                fmt_size(len(self.rsc.decompressed)), len(self.textures)))
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.textures))
        for i, t in enumerate(self.textures):
            px = len(t.pixel_data) if t.pixel_data else 0
            vals = (t.name, "%dx%d" % (t.width, t.height), t.format, fmt_size(px))
            for col, val in enumerate(vals):
                item = QtWidgets.QTableWidgetItem(val)
                if col == 0:
                    item.setText(ltr(val))
                else:
                    item.setTextAlignment(
                        int(QtCore.Qt.AlignmentFlag.AlignCenter))
                self.table.setItem(i, col, item)
        self.win.status("تم تحميل %s" % os.path.basename(path))

    def extract_dds(self):
        if not self.rsc or not self.textures:
            QtWidgets.QMessageBox.warning(self, "تنبيه", "حمّل ملفاً أولاً")
            return
        outdir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "اختر مجلد الحفظ")
        if not outdir:
            return
        textures = list(self.textures)

        def job():
            n = 0
            used = set()
            for i, t in enumerate(textures):
                if t.pixel_data is None:
                    continue
                stem = os.path.splitext(os.path.basename(t.name or ""))[0] \
                    or ("tex_%d" % i)
                for ch in '\\/:*?"<>|':
                    stem = stem.replace(ch, "_")
                base, k = stem, 1
                while stem.lower() in used:
                    stem = "%s_%d" % (base, k)
                    k += 1
                used.add(stem.lower())
                with open(os.path.join(outdir, stem + ".dds"), "wb") as fh:
                    fh.write(wtdmod.dds_export(t))
                n += 1
            return n

        def ok(n):
            self.win.status("تم استخراج %d صورة DDS" % n)
            QtWidgets.QMessageBox.information(
                self, "تم", "تم استخراج %d صورة DDS" % n)

        run_async(self, job, ok, busy="جارٍ الاستخراج...")

    def convert(self):
        path = self.path_edit.text().strip()
        if not self.rsc:
            QtWidgets.QMessageBox.warning(self, "تنبيه", "حمّل ملفاً أولاً")
            return
        lower = path.lower()
        if lower.endswith(".wtd"):
            out, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "احفظ CTD", os.path.splitext(path)[0] + ".ctd",
                "PS3 CTD (*.ctd)")
            if not out:
                return

            def job():
                return wtdmod.convert_to_ctd(open(path, "rb").read())

            def ok(data):
                with open(out, "wb") as fh:
                    fh.write(data)
                self.win.status("تم التحويل: %s" % os.path.basename(out))
                QtWidgets.QMessageBox.information(
                    self, "تم",
                    "تم تحويل القوام بنجاح (%s)\nجاهز للحقن في vehicles.img"
                    % fmt_size(len(data)))

            run_async(self, job, ok, busy="جارٍ التحويل...")
        elif lower.endswith(".wft"):
            out, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "احفظ CFT", os.path.splitext(path)[0] + ".cft",
                "PS3 CFT (*.cft)")
            if not out:
                return
            wft = wftmod.WftFile.load(path)
            cft = wft.to_ps3()
            with open(out, "wb") as fh:
                fh.write(cft)
            self.win.status("تم التحويل (تجريبي): %s" % os.path.basename(out))
            QtWidgets.QMessageBox.information(
                self, "تم (تجريبي)",
                "تم تحويل المجسم بتغليف تجريبي.\n"
                "البنية الداخلية محفوظة من PC وقد تحتاج تحقق على الجهاز.")
        else:
            QtWidgets.QMessageBox.warning(
                self, "تنبيه", "التحويل متاح من WTD أو WFT فقط (PC → PS3)")


class ManifestPage(QtWidgets.QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)
        title = QtWidgets.QLabel("الفهرسة")
        title.setObjectName("title")
        sub = QtWidgets.QLabel("فهرسة كل ملفات اللعبة والأرشيفات في ملف JSON")
        sub.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(sub)
        card = QtWidgets.QLabel(
            "يتم توليد manifest.json يتضمن:\n"
            "• كل الأرشيفات (RPF / IMG) بمحتوياتها\n"
            "• الأرشيفات المتداخلة (playerped.rpf وغيرها)\n"
            "• كل الملفات الحرة مع الأحجام\n"
            "• بيانات PARAM.SFO إن وُجدت")
        card.setObjectName("card")
        root.addWidget(card)
        row = QtWidgets.QHBoxLayout()
        self.out_edit = QtWidgets.QLineEdit(
            os.path.join(win.game_dir, "manifest.json"))
        self.out_edit.setLayoutDirection(QtCore.Qt.LayoutDirection.LeftToRight)
        b_pick = QtWidgets.QPushButton("استعراض")
        b_pick.clicked.connect(self.pick)
        b_run = QtWidgets.QPushButton("توليد الفهرس")
        b_run.setObjectName("primary")
        b_run.clicked.connect(self.run)
        row.addWidget(self.out_edit, 1)
        row.addWidget(b_pick)
        row.addWidget(b_run)
        root.addLayout(row)
        self.result = QtWidgets.QLabel("")
        self.result.setObjectName("subtitle")
        root.addWidget(self.result)
        root.addStretch(1)

    def pick(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "احفظ الفهرس", self.out_edit.text(), "JSON (*.json)")
        if path:
            self.out_edit.setText(path)

    def run(self):
        game = self.win.game_dir
        out = self.out_edit.text().strip()
        if not out:
            return

        def job():
            return manifestmod.write_manifest(game, out)

        def ok(m):
            self.result.setText(
                "تم ✓ — %d أرشيف • %d ملف حر" % (
                    len(m["archives"]), len(m["files"])))
            self.win.status("تم توليد الفهرس")
            QtWidgets.QMessageBox.information(
                self, "تم", "تم توليد الفهرس بنجاح")

        run_async(self, job, ok, busy="جارٍ الفهرسة (قد تستغرق دقيقة)...",)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1020, 680)
        settings = QtCore.QSettings("gtaivkit", "GTAIVModKit")
        self.game_dir = settings.value("game_dir", DEFAULT_GAME)
        central = QtWidgets.QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        hbox = QtWidgets.QHBoxLayout(central)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(0)
        self.pages = QtWidgets.QStackedWidget()
        nav = [("الرئيسية",), ("الأرشيفات",), ("السيارات",),
               ("التحويل والمستكشف",), ("الفهرسة",)]
        self.sidebar = Sidebar([(k, k) for k, in nav], self.nav)
        hbox.addWidget(self.sidebar)
        hbox.addWidget(self.pages, 1)
        self.home = HomePage(self)
        self.archives = ArchivesPage(self)
        self.cars = CarsPage(self)
        self.convert = ConvertPage(self)
        self.manifest = ManifestPage(self)
        for p in (self.home, self.archives, self.cars, self.convert,
                  self.manifest):
            self.pages.addWidget(p)
        self.setStatusBar(QtWidgets.QStatusBar())
        self.status("جاهز — مرحباً بك في GTAIV Mod Kit")
        self.pages.currentChanged.connect(self._page_changed)

    def nav(self, idx):
        self.pages.setCurrentIndex(idx)

    def _page_changed(self, idx):
        for i in range(self.sidebar.group.buttons().__len__()):
            self.sidebar.group.button(i).setChecked(i == idx)

    def pick_game_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "اختر مجلد USRDIR", self.home.dir_edit.text())
        if d:
            self.game_dir = d
            self.home.dir_edit.setText(d)
            QtCore.QSettings("gtaivkit", "GTAIVModKit").setValue(
                "game_dir", d)
            self.home.refresh()
            self.cars.img_edit.setText(
                os.path.join(d, carsmod.VEHICLES_IMG.replace("/", os.sep)))

    def status(self, msg):
        self.statusBar().showMessage(msg)


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setLayoutDirection(QtCore.Qt.LayoutDirection.RightToLeft)
    app.setStyleSheet(QSS)
    font = QtGui.QFont("Segoe UI", 10)
    app.setFont(font)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
