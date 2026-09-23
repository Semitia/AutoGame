"""Player-first Qt desktop client; battle runners remain separate processes."""
import copy
import datetime
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import uuid

ROOT = Path(__file__).resolve().parent
if (ROOT / '.local/python-deps').is_dir():
    sys.path.insert(0, str(ROOT / '.local/python-deps'))
try:
    from PySide6.QtCore import Qt, QTimer, QUrl, QEvent
    from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPen
    from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox,
        QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
        QHBoxLayout, QInputDialog, QLabel, QLayout, QLineEdit, QMainWindow, QMessageBox,
        QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
        QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QListWidget,
        QListWidgetItem, QAbstractItemView)
except ImportError:
    raise SystemExit('GUI 需要 Qt。请使用当前 Python 执行：python -m pip install -r requirements-gui.txt')

from gui_config import (CACHE, GAME, LINEUPS, atomic_json, hydrate_lineups,
    load_cache, prepare_launch, read_json, resolved, validate_tactics)
from gui_devices import discover_devices, parse_online
from skill_library import SkillLibrary


class PageWheel:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if isinstance(self, (QSpinBox, QDoubleSpinBox)):
            self.lineEdit().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel:
            self.wheelEvent(event)
            return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event):
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                QApplication.sendEvent(parent.viewport(), event)
                return
            parent = parent.parentWidget()
        event.ignore()


class QComboBox(PageWheel, QComboBox):
    pass


class QSpinBox(PageWheel, QSpinBox):
    pass


class QDoubleSpinBox(PageWheel, QDoubleSpinBox):
    pass


class SkillList(QListWidget):
    def __init__(self, values):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.addItems(values)
        self.setToolTip('拖动调整顺序，越靠上越优先。未加入的技能仍按原脚本规则选取。')

    def values(self):
        return [self.item(i).text() for i in range(self.count())]

    def toPlainText(self):
        return '\n'.join(self.values())

    def setPlainText(self, text):
        self.clear()
        self.addItems(list(dict.fromkeys(s.strip() for s in text.splitlines() if s.strip())))

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
ROLES = {'输出': 'damage', '控制': 'control', '辅助': 'support'}
COLORS = ['#7da8ff', '#e4b677', '#b59aff', '#7edbb8']
STYLE = '''
QMainWindow, QDialog { background: #10151f; }
QWidget { background: #10151f; color: #e9edf5; font-family: "Microsoft YaHei UI"; font-size: 12px; }
QFrame#sidebar { background: #151c28; border-right: 1px solid #293243; }
QFrame#card { background: #192231; border: 1px solid #2b3749; border-radius: 14px; }
QFrame#heroCard { background: #1b2535; border: 1px solid #334257; border-radius: 12px; }
QFrame#footer { background: #151d29; border-top: 1px solid #2b3749; }
QLabel { background: transparent; }
QWidget#fieldGroup { background: transparent; }
QLabel#eyebrow { color: #85b9a4; font-size: 10px; font-weight: 600; }
QLabel#title { font-size: 28px; font-weight: 700; }
QLabel#section { font-size: 16px; font-weight: 600; }
QLabel#muted { color: #98a8bd; }
QLabel#small { color: #98a8bd; font-size: 10px; }
QLabel#badge { color: #b4eed3; background: #203b36; border-radius: 9px; padding: 5px 10px; }
QLabel#warning { color: #e9bf7b; background: #352e25; border-radius: 8px; padding: 10px; }
QPushButton { background: #263346; border: 1px solid #3b4b62; border-radius: 8px; padding: 8px 14px; font-weight: 500; }
QPushButton:hover { background: #33455d; border-color: #6c8baa; }
QPushButton:pressed { background: #1e2b3c; }
QPushButton:disabled { color: #66778e; background: #1a2433; border-color: #293547; }
QPushButton#primary { background: #a5e7c7; border: 0; color: #102e24; font-size: 14px; font-weight: 700; padding: 12px 30px; }
QPushButton#primary:hover { background: #c1f4db; }
QPushButton#ghost { background: transparent; border: 0; color: #a6b6c9; padding: 7px 8px; }
QPushButton#ghost:hover { background: #263346; color: #eef4fc; }
QPushButton#nav { background: transparent; border: 0; text-align: left; padding: 12px 18px; color: #9aadc4; }
QPushButton#nav:checked { background: #263e3d; color: #b6f0d4; }
QPushButton#mode { text-align: left; background: #192231; border: 1px solid #2c394e; padding: 12px 16px; }
QPushButton#mode:checked { background: #213b37; border-color: #88d4b1; color: #c7f6df; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QListWidget {
 background: #111a28; border: 1px solid #344357; border-radius: 7px; padding: 6px 9px; selection-background-color: #375b60; }
QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus { border-color: #8bdbb9; }
QListWidget::item { padding: 5px; border-bottom: 1px solid #243247; }
QListWidget::item:selected { background: #355955; }
QComboBox { min-height: 22px; }
QComboBox::drop-down { border: 0; width: 23px; }
QComboBox QAbstractItemView { background: #1e2b3d; selection-background-color: #355955; padding: 4px; }
QSpinBox, QDoubleSpinBox { min-height: 22px; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #586d85; background: #101a27; }
QCheckBox::indicator:checked { background: #96ddbc; border-color: #b5f2d5; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #141d2b; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #41536b; min-height: 28px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QTableWidget { background: #182231; border: 1px solid #334359; border-radius: 8px; gridline-color: #2e3c50; }
QHeaderView::section { background: #243247; color: #b8c8dc; border: 0; padding: 9px; }
QToolTip { background: #e5f4ee; color: #152e28; border: 0; padding: 6px; }
'''
STYLE += f'''
QComboBox::down-arrow, QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({(ROOT/'gui_assets/down.svg').as_posix()}); width: 10px; height: 6px; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({(ROOT/'gui_assets/up.svg').as_posix()}); width: 10px; height: 6px; }}
QCheckBox::indicator:checked {{ image: url({(ROOT/'gui_assets/check.svg').as_posix()}); }}
'''


def label(text, kind=None, wrap=False):
    w = QLabel(text)
    if kind: w.setObjectName(kind)
    w.setWordWrap(wrap)
    return w


def button(text, callback, kind=None):
    w = QPushButton(text)
    if kind: w.setObjectName(kind)
    w.setCursor(Qt.PointingHandCursor)
    w.clicked.connect(callback)
    return w


def box(parent=None, margins=0, spacing=12, horizontal=False):
    layout = QHBoxLayout(parent) if horizontal else QVBoxLayout(parent)
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(spacing)
    return layout


def card():
    frame = QFrame()
    frame.setObjectName('card')
    return frame, box(frame, 18)


def combo(items, value=None):
    w = QComboBox()
    w.addItems(items)
    if value is not None: w.setCurrentText(str(value))
    return w


def spin(value, minimum=0, maximum=999, decimal=False):
    w = QDoubleSpinBox() if decimal else QSpinBox()
    w.setRange(minimum, maximum)
    if decimal: w.setDecimals(1)
    w.setValue(float(value) if decimal else int(value))
    return w


class Orbit(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(42, 42)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor('#779fbe'), 1.5))
        p.drawEllipse(3, 13, 36, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#a6e6c8'))
        p.drawEllipse(11, 9, 23, 23)
        p.setBrush(QColor('#355e69'))
        p.drawEllipse(22, 12, 8, 6)
        p.setBrush(QColor('#abc8ef'))
        p.drawEllipse(3, 21, 5, 5)


class HeroCard(QFrame):
    def __init__(self, index, slot, catalog, rank, changed, library, unclaim):
        super().__init__()
        self.setObjectName('heroCard')
        self.setMinimumWidth(175)
        self.slot = copy.deepcopy(slot)
        self.changed = changed
        self.library = library
        self.unclaim = unclaim
        layout = box(self, 12, 7)
        header = box(horizontal=True, spacing=8)
        token = label(f'{index+1:02}', 'section')
        token.setStyleSheet(f'color: {COLORS[index]}; background: #29384c; border-radius: 8px; padding: 7px;')
        header.addWidget(token)
        header.addWidget(label('出战位置', 'small'))
        header.addStretch()
        layout.addLayout(header)
        self.hero = QComboBox()
        self.hero.addItem('选择英雄', '')
        for key, item in catalog.items(): self.hero.addItem(item['name'], key)
        self.hero.setCurrentIndex(max(0, self.hero.findData(slot.get('hero', ''))))
        self.hero.setStyleSheet('font-size: 16px; font-weight: 600; padding-top: 8px; padding-bottom: 8px;')
        layout.addWidget(self.hero)
        self.role = combo(list(ROLES), next((k for k, v in ROLES.items() if v == slot.get('role')), '输出'))
        layout.addWidget(self.role)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.reserve = spin(slot.get('reserve', 0 if slot.get('role') == 'damage' else 2), 0, 99)
        self.minimum = spin(slot.get('min_remaining', 0), 0, 99)
        self.rank = spin(rank, 1, 4)
        self.reserve.setToolTip('超过这个数量优先合成；输出有空位时仍保留。')
        self.minimum.setToolTip('合成消耗两只后，至少保留几只该英雄。')
        for col, text, field in [(0, '保留阈值', self.reserve), (1, '至少留场', self.minimum), (2, '选卡顺位', self.rank)]:
            grid.addWidget(label(text, 'small'), 0, col)
            grid.addWidget(field, 1, col)
            field.setMinimumWidth(0)
            field.setMaximumWidth(72)
        layout.addLayout(grid)
        layout.addWidget(label('技能优先顺序 · 拖动排序', 'small'))
        self.buffs = SkillList(slot.get('buff_order', []))
        self.buffs.setFixedHeight(138)
        layout.addWidget(self.buffs)
        actions = box(horizontal=True, spacing=3)
        actions.addWidget(button('技能库 / 收录', self.pick_skills, 'ghost'))
        actions.addWidget(button('移除', self.remove_skill, 'ghost'))
        layout.addLayout(actions)
        self.hero.currentIndexChanged.connect(self.hero_changed)
        self.role.currentTextChanged.connect(changed)
        for w in (self.reserve, self.minimum, self.rank): w.valueChanged.connect(changed)
        self.buffs.model().rowsMoved.connect(self.skills_changed)
        self.buffs.model().rowsInserted.connect(self.skills_changed)
        self.buffs.model().rowsRemoved.connect(self.skills_changed)

    def skills_changed(self, *_):
        self.library.remember(self.hero.currentText() if self.hero.currentData() else '', self.buffs.values(), True)
        self.changed()

    def remove_skill(self):
        row = self.buffs.currentRow()
        if row >= 0: self.buffs.takeItem(row)

    def pick_skills(self):
        if not self.hero.currentData(): return
        name = self.hero.currentText()
        dialog = QDialog(self)
        dialog.setWindowTitle(name + ' · 技能库')
        dialog.setObjectName('skillLibraryDialog')
        dialog.resize(600, 520)
        layout = box(dialog, 18)
        layout.addWidget(label('已认领技能 · 双击加入优先级', 'section'))
        known = QListWidget()
        known.setObjectName('claimedSkills')
        known.addItems(self.library.choices(name))
        layout.addWidget(known)
        def add(title):
            if title and title not in self.buffs.values(): self.buffs.addItem(title)
        known.itemDoubleClicked.connect(lambda item: add(item.text()))
        def return_selected():
            item=known.currentItem()
            if item:
                self.unclaim(name,item.text())
                refresh()
        layout.addWidget(button('退回未认领', return_selected))
        layout.addWidget(label('未认领技能 · 双击直接认领标题', 'muted', True))
        observed = QListWidget()
        observed.setObjectName('unclaimedSkills')
        observed.setWordWrap(True)
        observed.setTextElideMode(Qt.ElideNone)
        observed.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        def refresh():
            known.clear(); known.addItems(self.library.choices(name))
            observed.clear()
            for text in self.library.observations(name):
                title = text.split(maxsplit=1)[0] if text.strip() else ''
                if not title:continue
                parts = text.strip().split(maxsplit=1)
                item = QListWidgetItem(title + ('\n' + parts[1] if len(parts)>1 else ''))
                item.setData(Qt.UserRole, text)
                item.setToolTip(text)
                observed.addItem(item)
        refresh()
        layout.addWidget(observed)
        def claim_skill(item=None):
            if item is not None:
                raw = item.data(Qt.UserRole)
                title, ok = raw.split(maxsplit=1)[0], True
            else:
                raw = None
                title, ok = QInputDialog.getText(dialog, '补充技能', '技能标题：')
            if ok and title.strip():
                title = title.strip()
                try:self.library.claim(name, title, raw or None)
                except ValueError as error:
                    QMessageBox.warning(dialog,'认领失败',str(error));return
                add(title)
                refresh()
        observed.itemDoubleClicked.connect(claim_skill)
        layout.addWidget(button('补充技能', lambda: claim_skill()))
        layout.addWidget(button('完成', dialog.accept, 'primary'))
        dialog.exec()

    def hero_changed(self, *_):
        # A previous hero's skill keywords must not silently become the new hero's tactics.
        self.buffs.model().blockSignals(True)
        self.buffs.clear()
        self.buffs.addItems(self.library.preferred(self.hero.currentText()))
        self.buffs.model().blockSignals(False)
        self.changed()

    def value(self):
        result = copy.deepcopy(self.slot)
        result.update(hero=self.hero.currentData(), role=ROLES[self.role.currentText()],
                      reserve=self.reserve.value(), min_remaining=self.minimum.value(),
                      buff_order=[s.strip() for s in self.buffs.toPlainText().replace('，', '\n').replace(',', '\n').splitlines() if s.strip()])
        return result


class LineupPanel(QWidget):
    def __init__(self, owner, key, title, readonly=False):
        super().__init__()
        self.owner, self.key, self.readonly = owner, key, readonly
        self.profile = copy.deepcopy(owner.profile[key])
        self.rows = []
        layout = box(self, spacing=12)
        heading = box(horizontal=True)
        heading.addWidget(label(title, 'section'))
        heading.addWidget(label('4 个出战位置', 'small'))
        heading.addStretch()
        if not readonly:
            heading.addWidget(button('导入阵容', self.import_, 'ghost'))
            heading.addWidget(button('导出', self.export, 'ghost'))
            heading.addWidget(button('添加英雄', self.add_hero, 'ghost'))
        layout.addLayout(heading)
        catalog = read_json(GAME/'heroes.json')
        names = {v['name'] for v in catalog.values()} | {v['name'] for v in self.profile.get('hero_definitions', {}).values()}
        extra = {k:v for k,v in owner.library.definitions().items() if v['name'] not in names}
        catalog.update(extra)
        catalog.update(self.profile.get('hero_definitions', {}))
        self.profile.setdefault('hero_definitions', {}).update(extra)
        priority = self.profile.get('buff_priority', [s['hero'] for s in self.profile['slots']])
        ranks = self.profile.get('_gui_ranks')
        row = box(horizontal=True, spacing=10)
        for i, slot in enumerate(self.profile['slots']):
            rank = ranks[i] if ranks else priority.index(slot['hero'])+1 if slot['hero'] in priority and slot['hero'] else i+1
            hero = HeroCard(i, slot, catalog, rank, self.edited, owner.library, owner.unclaim_skill)
            hero.setEnabled(not readonly)
            self.rows.append(hero)
            row.addWidget(hero, 1)
        layout.addLayout(row)
        tactics, inner = card()
        line = box(horizontal=True, spacing=10)
        line.addWidget(label('消费战术', 'section'))
        line.addSpacing(12)
        line.addWidget(label('下一次强化费', 'muted'))
        ratio = self.profile.get('price_ratio', {})
        self.upgrade = spin(ratio.get('upgrade', 2), .1, 100, True)
        self.summon = spin(ratio.get('summon', 1), .1, 100, True)
        self.upgrade.setFixedWidth(72)
        self.summon.setFixedWidth(72)
        line.addWidget(self.upgrade)
        line.addWidget(label(':'))
        line.addWidget(self.summon)
        line.addWidget(label('召唤费', 'muted'))
        line.addStretch()
        line.addWidget(label('相等时召唤', 'badge'))
        inner.addLayout(line)
        self.upgrade.setEnabled(not readonly)
        self.summon.setEnabled(not readonly)
        self.upgrade.valueChanged.connect(self.edited)
        self.summon.valueChanged.connect(self.edited)
        layout.addWidget(tactics)

    def value(self):
        result = copy.deepcopy(self.profile)
        result['slots'] = [r.value() for r in self.rows]
        ranks = [r.rank.value() for r in self.rows]
        result['_gui_ranks'] = ranks
        result['buff_priority'] = [slot['hero'] for _, slot in sorted(zip(ranks, result['slots']), key=lambda pair: pair[0])]
        result['price_ratio'] = {'upgrade': self.upgrade.value(), 'summon': self.summon.value()}
        return result

    def edited(self, *_):
        if self.readonly: return
        self.owner.profile[self.key] = self.value()
        self.owner.changed()

    def import_(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入阵容', str(GAME/'tactics'), '阵容 (*.json)')
        if not path: return
        try:
            profile = read_json(path)
            validate_tactics(profile)
            self.owner.library.seed(profile, read_json(GAME/'heroes.json'))
            profile.pop('_gui_ranks', None)
            self.owner.profile[self.key] = profile
            self.owner.rebuild_battle()
            self.owner.changed()
        except (OSError, ValueError, KeyError, TypeError) as error: self.owner.error(str(error))

    def export(self):
        try:
            value = self.value()
            self.owner.check_ranks(value)
            validate_tactics(value)
            path, _ = QFileDialog.getSaveFileName(self, '导出阵容', '我的阵容.json', '阵容 (*.json)')
            if path:
                value.pop('_gui_ranks', None)
                atomic_json(path, value)
        except (OSError, ValueError, KeyError, TypeError) as error: self.owner.error(str(error))

    def add_hero(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('添加英雄')
        dialog.setMinimumWidth(420)
        layout = box(dialog, 24)
        layout.addWidget(label('加入你的英雄库', 'section'))
        layout.addWidget(label('只填准确英雄名即可；战斗选卡文字会自动收录。', 'muted'))
        name, keywords = QLineEdit(), QLineEdit()
        name.setPlaceholderText('英雄名称')
        keywords.setPlaceholderText('识别关键词（可选），用逗号分隔')
        layout.addWidget(name)
        layout.addWidget(keywords)
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.button(QDialogButtonBox.Save).setText('添加')
        actions.button(QDialogButtonBox.Cancel).setText('取消')
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        if dialog.exec() != QDialog.Accepted: return
        if not name.text().strip(): return self.owner.error('请输入英雄的准确名称')
        value = self.value()
        self.owner.library.add_hero({
            'name': name.text().strip(),
            'buff_keywords': [s.strip() for s in keywords.text().replace('，', ',').split(',') if s.strip()]})
        value.setdefault('hero_definitions', {}).update(self.owner.library.definitions())
        self.owner.profile[self.key] = value
        self.owner.rebuild_battle()
        self.owner.changed()


class App(QMainWindow):
    def unclaim_skill(self, name, title):
        self.library.unclaim(name,title)
        # Remove the retracted assignment from all cached drafts, otherwise a
        # later profile switch/seed would silently restore the old ownership.
        base=read_json(GAME/'heroes.json')
        for profile in self.data['profiles'].values():
            for key in LINEUPS:
                lineup=profile.get(key,{})
                catalog=dict(base,**lineup.get('hero_definitions',{}))
                for slot in lineup.get('slots',[]):
                    if catalog.get(slot.get('hero'),{}).get('name')==name:
                        slot['buff_order']=[s for s in slot.get('buff_order',[]) if s!=title]
        for panel in self.lineups.values():
            for row in panel.rows:
                if row.hero.currentText()!=name:continue
                row.buffs.model().blockSignals(True)
                for i in reversed(range(row.buffs.count())):
                    if row.buffs.item(i).text()==title:row.buffs.takeItem(i)
                row.buffs.model().blockSignals(False)
            panel.edited()
        self.changed()

    def __init__(self):
        super().__init__()
        self.setWindowTitle('蔚蓝星球 · 出战准备')
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1340, screen.width()-60), min(960, screen.height()-60))
        self.setMinimumSize(1100, 700)
        self.move(screen.x()+30, screen.y()+20)
        self.jobs, self.lineups = [], {}
        self.events = queue.Queue()
        self.online_devices = []
        self.device_labels = {}
        self.device_identities = {}
        self.device_scan_busy = False
        self.device_scan_state = '正在查找在线设备…'
        self.loading = True
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(500)
        self.save_timer.timeout.connect(self.save)
        self.data = load_cache()
        self.library = SkillLibrary(CACHE.parent/'hero-skills.sqlite3')
        catalog = read_json(GAME/'heroes.json')
        for path in (GAME/'tactics').glob('*.json'):
            self.library.seed(read_json(path), catalog)
        for profile in self.data['profiles'].values():
            for key in LINEUPS:
                if isinstance(profile.get(key), dict): self.library.seed(profile[key], catalog)
        self.current = self.data['selected']
        self.profile = self.data['profiles'][self.current]
        self.migration_errors = []
        self.hydrate()
        self.library.migrate_legacy_claims()
        self.build_ui()
        self.loading = False
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(1000)
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start()
        self.device_timer = QTimer(self)
        self.device_timer.setInterval(5000)
        self.device_timer.timeout.connect(self.refresh_devices)
        self.device_timer.start()
        self.refresh_devices()
        self.changed()
        if self.migration_errors: self.notice.setText('部分旧阵容无法导入，请重新选择英雄：' + '; '.join(self.migration_errors))

    def hydrate(self):
        for key, old_key in LINEUPS.items():
            if key in self.profile: continue
            part = {old_key: self.profile.get(old_key, '')}
            try:
                hydrate_lineups(part)
                self.profile[key] = part[key]
            except (OSError, ValueError, TypeError) as error:
                self.migration_errors.append(str(error))
                empty = {}
                hydrate_lineups(empty)
                self.profile[key] = empty[key]
        for key in LINEUPS:
            self.library.seed(self.profile[key], read_json(GAME/'heroes.json'))

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = box(root, horizontal=True, spacing=0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(194)
        side = box(sidebar, 18, 14)
        brand = box(horizontal=True, spacing=9)
        brand.addWidget(Orbit())
        words = box(spacing=2)
        words.addWidget(label('蔚蓝星球', 'section'))
        words.addWidget(label('BATTLE COMPANION', 'small'))
        brand.addLayout(words)
        side.addLayout(brand)
        side.addSpacing(24)
        self.nav = []
        for index, text in enumerate(('出战准备', '战斗记录', '设置')):
            b = button(text, lambda checked=False, i=index: self.navigate(i), 'nav')
            b.setCheckable(True)
            self.nav.append(b)
            side.addWidget(b)
        self.nav[0].setChecked(True)
        side.addStretch()
        side.addWidget(label('我的配置', 'eyebrow'))
        self.profile_picker = combo(list(self.data['profiles']), self.current)
        self.profile_picker.currentTextChanged.connect(self.switch_profile)
        side.addWidget(self.profile_picker)
        side.addWidget(button('＋ 新建配置', self.clone, 'ghost'))
        side.addSpacing(8)
        self.saved = label('本地自动保存', 'small', True)
        side.addWidget(self.saved)
        side.addWidget(button('使用说明 ↗', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ROOT/'docs/GUI.md'))), 'ghost'))
        root_layout.addWidget(sidebar)
        right = QWidget()
        right_layout = box(right, spacing=0)
        self.pages = QStackedWidget()
        right_layout.addWidget(self.pages, 1)
        self.battle_scroll = QScrollArea()
        self.battle_scroll.setWidgetResizable(True)
        self.pages.addWidget(self.battle_scroll)
        self.build_records()
        self.build_settings()
        self.rebuild_battle()
        footer = QFrame()
        footer.setObjectName('footer')
        foot = box(footer, 18, horizontal=True)
        status = box(spacing=4)
        self.notice = label('准备就绪', 'section', True)
        self.summary = label('', 'small')
        status.addWidget(self.notice)
        status.addWidget(self.summary)
        foot.addLayout(status, 1)
        foot.addWidget(button('检查配置', self.check, 'ghost'))
        self.start_button = button('开始战斗  →', self.start, 'primary')
        foot.addWidget(self.start_button)
        right_layout.addWidget(footer)
        root_layout.addWidget(right, 1)
        self.update_summary()

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        for i, b in enumerate(self.nav): b.setChecked(i == index)

    def field(self, key, widget, global_=False):
        data = self.data if global_ else self.profile
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(data.get(key)))
            widget.toggled.connect(lambda value: self.set_field(key, value, global_))
        elif isinstance(widget, QComboBox):
            widget.setCurrentText(str(data.get(key, '')))
            widget.currentTextChanged.connect(lambda value: self.set_field(key, value, global_))
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.setValue(float(data.get(key, 0))) if isinstance(widget, QDoubleSpinBox) else widget.setValue(int(data.get(key, 0)))
            widget.valueChanged.connect(lambda value: self.set_field(key, str(value), global_))
        else:
            widget.setText(str(data.get(key, '')))
            widget.textChanged.connect(lambda value: self.set_field(key, value, global_))
        return widget

    def set_field(self, key, value, global_=False):
        (self.data if global_ else self.profile)[key] = value
        self.changed()

    def labeled(self, title, widget):
        frame = QWidget()
        frame.setObjectName('fieldGroup')
        layout = box(frame, spacing=6)
        layout.addWidget(label(title, 'small'))
        layout.addWidget(widget)
        return frame

    def rebuild_battle(self):
        previous = self.battle_scroll.takeWidget()
        if previous: previous.deleteLater()
        content = QWidget()
        layout = box(content, 22, 12)
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.battle_scroll.setWidget(content)
        self.lineups, self.device_boxes = {}, []
        headline = box(horizontal=True)
        titles = box(spacing=3)
        titles.addWidget(label('PLAY YOUR WAY', 'eyebrow'))
        titles.addWidget(label('准备好，下一场冒险。', 'title'))
        headline.addLayout(titles)
        headline.addStretch()
        headline.addWidget(label('配置自动保存', 'badge'))
        layout.addLayout(headline)
        modes = box(horizontal=True, spacing=12)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for key, title in [('单人战术', '主线挑战\n自由阵容 · 单局 / 挂机'), ('双人合作', '双人合作\n双队协作 · 单局挑战')]:
            b = button(title, lambda checked=False, k=key: self.change_mode(k), 'mode')
            b.setMinimumHeight(54)
            b.setCheckable(True)
            b.setChecked(key == self.profile['mode'])
            self.mode_group.addButton(b)
            modes.addWidget(b, 1)
        layout.addLayout(modes)
        coop = self.profile['mode'] == '双人合作'
        setup, setup_layout = card()
        row = box(horizontal=True, spacing=14)
        stage = self.field('stage', spin(1, 1, 999))
        stage.setPrefix('第 ')
        stage.setSuffix(' 层' if coop else ' 关')
        stage.setStyleSheet('font-size: 19px; font-weight: 600;')
        row.addWidget(self.labeled('挑战层数' if coop else '目标关卡', stage), 1)
        if not coop:
            self.loop = combo(['打一局', '连续挑战', '清空体力'])
            self.loop.setCurrentText('清空体力' if self.profile['until_stamina'] else '打一局' if int(self.profile['runs']) == 1 else '连续挑战')
            self.loop.currentTextChanged.connect(self.change_loop)
            row.addWidget(self.labeled('挑战方式', self.loop), 1)
            self.runs = self.field('runs', spin(1, 1, 999))
            self.runs.setSuffix(' 局')
            self.runs.setEnabled(self.loop.currentText() == '连续挑战')
            row.addWidget(self.labeled('挑战次数', self.runs), 1)
        minutes = self.field('minutes', spin(20, 1, 1440, True))
        minutes.setSuffix(' 分钟')
        row.addWidget(self.labeled('最长运行时间', minutes), 1)
        setup_layout.addLayout(row)
        layout.addWidget(setup)
        self.device_status = label(self.device_scan_state, 'small')
        layout.addWidget(self.device_status)
        if coop:
            layout.addWidget(label('合作仅开一局。请核对双方昵称与实际阵容；当前版本仍待实战验收。', 'warning', True))
            for side, title in [('host', '房主阵容'), ('guest', '访客阵容')]:
                row = box(horizontal=True)
                row.addWidget(label('房主' if side == 'host' else '访客', 'section'))
                nickname = self.field(side+'_name', QLineEdit())
                nickname.setPlaceholderText('游戏内准确昵称')
                row.addWidget(nickname, 1)
                row.addWidget(self.device(side+'_device'), 1)
                if side == 'host': row.addWidget(button('刷新设备', self.refresh_devices, 'ghost'))
                layout.addLayout(row)
                panel = LineupPanel(self, side+'_lineup', title)
                self.lineups[side+'_lineup'] = panel
                layout.addWidget(panel)
        else:
            row = box(horizontal=True)
            row.addWidget(label('出战设备', 'muted'))
            row.addWidget(self.device('device'), 1)
            row.addWidget(button('刷新设备', self.refresh_devices, 'ghost'))
            row.addStretch()
            layout.addLayout(row)
            panel = LineupPanel(self, 'lineup', '我的出战阵容')
            self.lineups['lineup'] = panel
            layout.addWidget(panel)
        options, opts = card()
        row = box(horizontal=True)
        row.addWidget(label('开战与停止', 'section'))
        row.addStretch()
        if coop:
            row.addWidget(self.field('battle_only', QCheckBox('接管已开始的战斗')))
            side_choice = QComboBox()
            for title, data in [('同时控制双方', '双方'), ('只控制房主', 'host'), ('只控制访客', 'guest')]: side_choice.addItem(title, data)
            side_choice.setCurrentIndex(max(0, side_choice.findData(self.profile['only_side'])))
            side_choice.currentIndexChanged.connect(lambda: self.set_field('only_side', side_choice.currentData()))
            row.addWidget(side_choice)
        else:
            entry = self.field('entry', combo(['从首页开始', '空棋盘接管', '暂停局接管', '恢复状态文件']))
            entry.currentTextChanged.connect(lambda text: self.choose_state('state') if text == '恢复状态文件' else None)
            row.addWidget(entry)
            row.addWidget(self.field('stop_on_loss', QCheckBox('失败后停止')))
        opts.addLayout(row)
        layout.addWidget(options)
        layout.addStretch()

    def device(self, key):
        w = QComboBox()
        w.device_key = key
        w.setPlaceholderText('按模拟器窗口名称选择')
        self.fill_device_box(w)
        w.currentIndexChanged.connect(lambda: self.set_field(key, w.currentData() or ''))
        self.device_boxes.append(w)
        return w

    def fill_device_box(self, w):
        selected = self.profile[w.device_key]
        entries = [(self.device_labels.get(serial, serial), serial) for serial in self.online_devices]
        if selected and selected not in self.online_devices:
            entries.append((f'{self.device_labels.get(selected, selected)} · 未连接', selected))
        if entries == [(w.itemText(i), w.itemData(i)) for i in range(w.count())]: return
        w.blockSignals(True)
        w.clear()
        for text, serial in entries: w.addItem(text, serial)
        w.setCurrentIndex(w.findData(selected) if selected else -1)
        w.blockSignals(False)

    def change_mode(self, key):
        if self.profile['mode'] == key: return
        self.profile['mode'] = key
        self.rebuild_battle()
        self.changed()

    def change_loop(self, value):
        self.profile['until_stamina'] = value == '清空体力'
        if value == '打一局': self.profile['runs'] = '1'
        if value == '连续挑战' and int(self.profile['runs']) == 1: self.profile['runs'] = '3'
        self.runs.setValue(int(self.profile['runs']))
        self.runs.setEnabled(value == '连续挑战')
        self.changed()

    def build_settings(self):
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.pages.addWidget(self.settings_scroll)
        self.rebuild_settings()

    def rebuild_settings(self):
        previous = self.settings_scroll.takeWidget()
        if previous: previous.deleteLater()
        page = QWidget()
        layout = box(page, 28, 20)
        layout.addWidget(label('设置', 'title'))
        layout.addWidget(label('环境配置通常只需设置一次。日常出战都在主界面完成。', 'muted'))
        frame, inner = card()
        inner.addWidget(label('运行环境', 'section'))
        for key, title in [('python', 'Python'), ('adb', 'ADB'), ('manager', 'MuMuManager')]:
            row = box(horizontal=True)
            field = self.field(key, QLineEdit(), True)
            row.addWidget(self.labeled(title, field), 1)
            row.addWidget(button('选择', lambda checked=False, w=field: self.choose_exe(w), 'ghost'))
            inner.addLayout(row)
        layout.addWidget(frame)
        frame, inner = card()
        inner.addWidget(label('当前配置 · 高级选项', 'section'))
        inner.addWidget(self.labeled('独立运行目录', self.field('runtime', QLineEdit())))
        for key, title in [('state', '主线战斗状态'), ('host_state', '房主检查点'), ('guest_state', '访客检查点')]:
            row = box(horizontal=True)
            field = self.field(key, QLineEdit())
            row.addWidget(self.labeled(title, field), 1)
            row.addWidget(button('选择', lambda checked=False, k=key, w=field: self.choose_state(k, w), 'ghost'))
            inner.addLayout(row)
        inner.addWidget(button('清除当前配置的停止标记', self.clear_stop))
        layout.addWidget(frame)
        self.device_detail = QPlainTextEdit()
        self.device_detail.setReadOnly(True)
        self.device_detail.setPlaceholderText('刷新设备后的连接详情会显示在这里。')
        self.device_detail.setMaximumHeight(130)
        layout.addWidget(self.device_detail)
        layout.addStretch()
        self.settings_scroll.setWidget(page)

    def build_records(self):
        page = QWidget()
        layout = box(page, 28, 18)
        layout.addWidget(label('战斗记录', 'title'))
        layout.addWidget(label('本次打开期间启动的任务。选中任务后查看日志或请求停止。', 'muted'))
        self.job_list = QTableWidget(0, 4)
        self.job_list.setHorizontalHeaderLabels(['配置', '设备', '进程', '状态'])
        self.job_list.horizontalHeader().setStretchLastSection(True)
        self.job_list.setSelectionBehavior(QTableWidget.SelectRows)
        self.job_list.setSelectionMode(QTableWidget.SingleSelection)
        self.job_list.setEditTriggers(QTableWidget.NoEditTriggers)
        self.job_list.setMaximumHeight(230)
        self.job_list.itemSelectionChanged.connect(self.show_log)
        layout.addWidget(self.job_list)
        row = box(horizontal=True)
        row.addWidget(button('停止选中任务', self.stop))
        row.addWidget(button('打开战斗记录目录', self.open_runtime, 'ghost'))
        row.addStretch()
        layout.addLayout(row)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setPlaceholderText('还没有战斗记录。配置好阵容后，就可以开始了。')
        self.logs.setFont(QFont('Consolas', 10))
        layout.addWidget(self.logs, 1)
        self.pages.addWidget(page)

    def choose_exe(self, widget):
        path, _ = QFileDialog.getOpenFileName(self, '选择程序', '', '可执行文件 (*.exe)')
        if path: widget.setText(path)

    def choose_state(self, key, widget=None):
        path, _ = QFileDialog.getOpenFileName(self, '选择同一场战斗的状态文件', str(ROOT/'runtime'), '状态文件 (*.json)')
        if path:
            self.profile[key] = path
            if widget: widget.setText(path)
            else: self.rebuild_settings()
            self.changed()

    def changed(self, *_):
        if self.loading: return
        self.saved.setText('正在保存…')
        self.save_timer.start()
        self.update_summary()

    def save(self):
        self.save_timer.stop()
        self.data['selected'] = self.current
        self.data['profiles'][self.current] = self.profile
        try:
            atomic_json(CACHE, self.data)
            self.saved.setText('● 已保存到本地')
            return True
        except OSError as error:
            self.saved.setText('保存失败：' + str(error))
            return False

    def switch_profile(self, name):
        if not name or self.loading or name == self.current: return
        if not self.save():
            self.profile_picker.blockSignals(True)
            self.profile_picker.setCurrentText(self.current)
            self.profile_picker.blockSignals(False)
            return
        self.current = name
        self.profile = self.data['profiles'][name]
        self.hydrate()
        self.rebuild_battle()
        self.rebuild_settings()
        self.changed()

    def clone(self):
        name, ok = QInputDialog.getText(self, '新建配置', '给这套配置起个名字，例如「大号日常」：')
        if not ok or not name.strip(): return
        name = name.strip()
        if name in self.data['profiles']: return self.error('这个配置名称已经存在')
        if not self.save(): return
        p = copy.deepcopy(self.profile)
        p['runtime'] = str(ROOT/'runtime/gui'/uuid.uuid4().hex[:12])
        self.data['profiles'][name] = p
        self.profile_picker.addItem(name)
        self.profile_picker.setCurrentText(name)

    def update_summary(self):
        if not hasattr(self, 'summary'): return
        p = self.profile
        mode = {'单人战术': '主线挑战', '双人合作': '双人合作'}[p['mode']]
        count = '合作单局' if p['mode'] == '双人合作' else '清空体力' if p['until_stamina'] else f'{p["runs"]} 局'
        stage = p['stage']
        self.summary.setText(f'{self.current}  ·  {mode} / {stage}  ·  {count}  ·  最长 {p["minutes"]} 分钟')

    @staticmethod
    def check_ranks(lineup):
        if '_gui_ranks' in lineup and sorted(lineup['_gui_ranks']) != [1, 2, 3, 4]:
            raise ValueError('四位英雄的选卡优先级必须分别为 1、2、3、4，不能重复。')

    def launch_spec(self):
        p = copy.deepcopy(self.profile)
        keys = ['lineup']
        if p['mode'] == '双人合作': keys = [side+'_lineup' for side in ('host', 'guest') if p['only_side'] in ('双方', side)]
        for key in keys:
            self.check_ranks(p[key])
            if any(not slot['hero'] for slot in p[key]['slots']): raise ValueError('请先为每个出战位置选择英雄。')
        return prepare_launch(self.data, p)

    def check(self):
        try:
            self.launch_spec()
            self.notice.setText('配置检查通过，请核对游戏内阵容后出战。')
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error: self.error(str(error))

    def error(self, text):
        self.notice.setText(text)

    def refresh_devices(self):
        if self.device_scan_busy: return
        self.device_scan_busy = True
        adb = self.data['adb']
        manager = self.data['manager']
        def work():
            try:
                result = discover_devices(adb, manager)
                self.events.put(('devices', (adb, result)))
            except (OSError, ValueError, subprocess.TimeoutExpired) as error: self.events.put(('device_error', (adb, str(error))))
        threading.Thread(target=work, daemon=True).start()

    def start(self):
        try:
            args, env, runtime, devices = self.launch_spec()
            identities = [self.device_identities.get(serial, serial) for serial in devices]
            if len(identities) != len(set(identities)):
                raise ValueError('房主和访客指向同一个模拟器窗口，请选择两个不同的窗口。')
            for job in self.jobs:
                if job['process'].poll() is None and (job['runtime'] == runtime or set(job['devices']) & set(devices)):
                    raise ValueError('该设备或运行目录已有任务，请先停止并等待退出。')
            if (runtime/'STOP').exists(): raise ValueError('上次任务留下了停止标记。查看记录后，可在设置中清除。')
            if not self.save(): raise ValueError('配置未能保存，请检查目录权限。')
            runtime.mkdir(parents=True, exist_ok=True)
            log = runtime / ('gui-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6] + '.log')
            with log.open('wb') as stream:
                process = subprocess.Popen(args, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
            job = dict(process=process, runtime=runtime, devices=devices, profile=self.current, log=log, stopping=False)
            self.jobs.append(job)
            row = self.job_list.rowCount()
            self.job_list.insertRow(row)
            for col, value in enumerate((self.current, ', '.join(devices), str(process.pid), '运行中')):
                self.job_list.setItem(row, col, QTableWidgetItem(value))
            self.job_list.selectRow(row)
            self.navigate(1)
            self.notice.setText('战斗已启动。新修改会用于下一场战斗。')
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error: self.error(str(error))

    def selected_job(self):
        row = self.job_list.currentRow()
        return self.jobs[row] if 0 <= row < len(self.jobs) else None

    def stop(self):
        job = self.selected_job()
        if not job or job['process'].poll() is not None: return
        try:
            (job['runtime']/'STOP').touch()
            job['stopping'] = True
            self.notice.setText('正在等待安全停止。合作模式停止脚本不会暂停游戏。')
        except OSError as error: self.error(str(error))

    def clear_stop(self):
        try:
            if not self.profile['runtime'].strip(): raise ValueError('请先指定运行目录。')
            runtime = resolved(self.profile['runtime'])
            if any(j['runtime'] == runtime and j['process'].poll() is None for j in self.jobs): raise ValueError('该任务尚未退出。')
            (runtime/'STOP').unlink(missing_ok=True)
            self.notice.setText('停止标记已清除，可以重新出战。')
        except (OSError, ValueError) as error: self.error(str(error))

    def open_runtime(self):
        job = self.selected_job()
        path = job['runtime'] if job else resolved(self.profile['runtime'])
        try:
            path.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except OSError as error: self.error(str(error))

    @staticmethod
    def tail(path, size):
        with path.open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell()-size))
            return stream.read().decode('utf-8', errors='replace')

    def show_log(self):
        job = self.selected_job()
        if not job: return
        try:
            text = self.tail(job['log'], 48000)
            candidates = list(job['runtime'].glob('runs/*/events.jsonl')) + list(job['runtime'].glob('*/20*/events.jsonl'))
            if candidates:
                latest = max(candidates, key=lambda p: p.stat().st_mtime)
                if latest.stat().st_mtime >= job['log'].stat().st_ctime:
                    text += '\n\n最近战斗事件\n' + self.tail(latest, 16000)
            text = text or '等待战斗脚本输出…'
            if self.logs.toPlainText() != text:
                scroll = self.logs.verticalScrollBar()
                end, position = scroll.value() >= scroll.maximum(), scroll.value()
                self.logs.setPlainText(text)
                scroll.setValue(scroll.maximum() if end else position)
        except OSError as error: self.error(str(error))

    def poll(self):
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind in ('devices', 'device_error'):
                self.device_scan_busy = False
                source, value = value
                if source != self.data['adb']: continue
            if kind == 'devices':
                # String payloads remain useful for offline fixtures and raw ADB-only discovery.
                result = value if isinstance(value, dict) else dict(raw=value, serials=parse_online(value), labels={}, identities={})
                self.device_detail.setPlainText(result['raw'] + '\n' + '\n'.join(result['labels'].values()) + '\n' + result.get('note', ''))
                self.online_devices = result['serials']
                self.device_labels = result['labels']
                self.device_identities = result['identities']
                self.device_scan_state = f'{len(self.online_devices)} 台设备在线 · 每 5 秒自动更新，请选择对应账号' if self.online_devices else '暂未发现在线设备 · 请确认模拟器已启动并启用 ADB'
                self.update_devices()
            elif kind == 'device_error':
                self.online_devices = []
                self.device_scan_state = '设备查询失败：' + value
                self.device_detail.setPlainText(self.device_scan_state)
                self.update_devices()
            else: self.error(value)
        for i, job in enumerate(self.jobs):
            code = job['process'].poll()
            text = ('等待停止' if job['stopping'] else '运行中') if code is None else f'已退出 · {code}'
            self.job_list.item(i, 3).setText(text)
        if self.pages.currentIndex() == 1: self.show_log()

    def update_devices(self):
        for w in self.device_boxes:
            # Avoid closing an open popup while a player is selecting a device.
            self.fill_device_box(w)
        self.device_status.setText(self.device_scan_state)

    def closeEvent(self, event):
        if any(j['process'].poll() is None for j in self.jobs):
            self.navigate(1)
            self.notice.setText('还有任务运行，请先停止并等待退出。')
            event.ignore()
        elif self.save():
            self.save_timer.stop()
            self.poll_timer.stop()
            self.device_timer.stop()
            event.accept()
        else: event.ignore()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    try:
        window = App()
    except (OSError, ValueError, TypeError, KeyError) as error:
        QMessageBox.critical(None, '无法读取本地配置', f'{error}\n原配置已保留，请检查 config/gui.json。')
        return 1
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
