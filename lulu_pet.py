# -*- coding: utf-8 -*-
"""
水豚噜噜桌面宠物  v0.1
=====================
一只住在桌面上的水豚噜噜：会发呆、眨眼、到处闲逛、打盹，能拖动、能摸头。

运行环境：Python 3.10+ / PySide6
启动方式：双击「启动桌宠.vbs」（无黑窗），或运行  pythonw lulu_pet.py

状态机（后续新增玩法时在这里扩展即可）：
    IDLE  原地待机：呼吸、眨眼、偶尔做表情
    WALK  沿屏幕底部闲逛
    DRAG  被鼠标拎起来
    HAPPY 被摸头后的开心反应
    SLEEP 长时间没人理就趴着睡觉，冒 Zzz
"""
import json
import logging
import math
import os
import random
import sys
import time

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, QSharedMemory
from PySide6.QtGui import (
    QPixmap, QPainter, QIcon, QColor, QFont, QAction, QTransform,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QMenu, QSystemTrayIcon, QMessageBox,
)

# ---------------------------------------------------------------- 路径与常量
ROOT = os.path.dirname(os.path.abspath(__file__))
ASSET_DIR = os.path.join(ROOT, "assets", "pet")
CONFIG_PATH = os.path.join(ROOT, "config.json")
LOG_DIR = os.path.join(ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(LOG_DIR, "pet.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)

IDLE, WALK, DRAG, HAPPY, SLEEP = "idle", "walk", "drag", "happy", "sleep"

STAND_H = 320          # 站立素材逻辑高度
SLEEP_H = 210          # 睡姿素材逻辑高度
TICK_MS = 33           # 约 30fps
SLEEP_AFTER = 35       # 无交互多少秒后睡觉
WALK_SPEED = 95        # px / 秒

HAPPY_LINES = ["噜噜~", "嘿嘿，好舒服", "橘子还在头上吗？", "再摸一下嘛",
               "噜噜今天也很困", "要一起泡温泉吗？", "别摸啦，好痒~", "今天也要加油哦"]
WAKE_LINES = ["唔……再睡五分钟……", "早安呀", "噜噜醒了", "是谁叫醒了噜噜"]
WALK_LINES = ["出去溜达一圈~", "散步有助于消化", "噜噜出发啦"]

FRAMES = {
    IDLE:  "idle",
    WALK:  "walk1",
    DRAG:  "drag",
    HAPPY: "happy",
    SLEEP: "sleep",
}


# ---------------------------------------------------------------- 配置
def load_config():
    cfg = {"scale": 1.0, "x": None, "y": None}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning("保存配置失败: %s", e)


# ---------------------------------------------------------------- 开机自启
def autostart_supported():
    return sys.platform == "win32"


def autostart_on():
    if not autostart_supported():
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.QueryValueEx(key, "LuluPet")
        key.Close()
        return True
    except OSError:
        return False


def set_autostart(on):
    if not autostart_supported():
        return
    import winreg
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0, winreg.KEY_SET_VALUE)
    if on:
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pyw):
            pyw = sys.executable
        cmd = '"%s" "%s"' % (pyw, os.path.join(ROOT, "lulu_pet.py"))
        winreg.SetValueEx(key, "LuluPet", 0, winreg.REG_SZ, cmd)
        logging.info("已设置开机自启: %s", cmd)
    else:
        try:
            winreg.DeleteValue(key, "LuluPet")
        except FileNotFoundError:
            pass
        logging.info("已取消开机自启")
    key.Close()


# ---------------------------------------------------------------- 桌宠主窗口
class PetWindow(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.scale = float(cfg.get("scale", 1.0))

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

        # 素材
        self.pix = {}
        for name in ["idle", "blink", "walk1", "walk2", "drag",
                     "sleep", "happy", "shy"]:
            p = QPixmap(os.path.join(ASSET_DIR, name + ".png"))
            if p.isNull():
                logging.error("素材加载失败: %s.png", name)
            self.pix[name] = p
        self._frame_cache = {}

        # 窗口尺寸（按最大站立帧 + 动画余量）
        self.win_w = int(270 * self.scale)
        self.win_h = int(430 * self.scale)
        self.setFixedSize(self.win_w, self.win_h)

        # 状态
        self.state = IDLE
        self.state_since = time.monotonic()
        self.state_until = time.monotonic() + 6
        self.facing = 1                 # 1 朝右（正面图无所谓），-1 朝左
        self.walk_phase = 0.0
        self.next_blink = time.monotonic() + random.uniform(1.5, 4)
        self.blink_until = 0
        self.last_interact = time.monotonic()
        self.bubble = None              # {"text", "until"}
        self.zzz = []                   # 睡觉的 Z 粒子
        self.next_zzz = 0
        self.idle_face = "idle"         # idle 时偶尔切 happy/shy
        self.idle_face_until = 0

        # 拖拽
        self._press_pos = None
        self._press_win_pos = None
        self._moved = False
        self._menu_checks = {}

        # 初始位置：默认屏幕右下角；若配置位置已在所有屏幕之外则回退
        screen = QApplication.primaryScreen().availableGeometry()
        x, y = cfg.get("x"), cfg.get("y")
        on_screen = False
        if x is not None and y is not None:
            from PySide6.QtCore import QRect
            probe = QRect(int(x), int(y), self.win_w, self.win_h)
            on_screen = any(probe.intersects(s.availableGeometry())
                            for s in QApplication.screens())
        if not on_screen:
            x = screen.right() - self.win_w - 40
            y = screen.bottom() - self.win_h + 12
        self.move(int(x), int(y))

        # 定时器
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)

        self._build_tray()
        self.enter_state(IDLE)

    # ------------------------------------------------------------- 托盘/菜单
    def _build_tray(self):
        icon = QIcon(self.pix["idle"])
        self.setWindowIcon(icon)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logging.warning("系统托盘不可用")
            self.tray = None
            return
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("水豚噜噜")
        self.tray.activated.connect(self._tray_activated)
        self.tray.setContextMenu(self._build_menu())
        self.tray.show()

    def _build_menu(self):
        menu = QMenu()
        act_pet = QAction("摸摸噜噜", self)
        act_pet.triggered.connect(self.action_pet)
        menu.addAction(act_pet)

        act_walk = QAction("出去散步", self)
        act_walk.triggered.connect(lambda: self.enter_state(WALK))
        menu.addAction(act_walk)

        act_idle = QAction("原地待着", self)
        act_idle.triggered.connect(lambda: self.enter_state(IDLE))
        menu.addAction(act_idle)

        act_sleep = QAction("小睡一会", self)
        act_sleep.triggered.connect(lambda: self.enter_state(SLEEP))
        menu.addAction(act_sleep)

        menu.addSeparator()

        size_menu = menu.addMenu("大小")
        self._menu_checks["size"] = {}
        for label, val in [("小", 0.8), ("中", 1.0), ("大", 1.25)]:
            a = QAction(label, self, checkable=True)
            a.setChecked(abs(self.scale - val) < 0.01)
            a.triggered.connect(lambda _=False, v=val: self.set_scale(v))
            size_menu.addAction(a)
            self._menu_checks["size"][val] = a

        if autostart_supported():
            act_auto = QAction("开机自动启动", self, checkable=True)
            act_auto.setChecked(autostart_on())
            act_auto.triggered.connect(self._toggle_autostart)
            menu.addAction(act_auto)
            self._menu_checks["autostart"] = act_auto

        menu.addSeparator()
        act_about = QAction("关于噜噜", self)
        act_about.triggered.connect(self.show_about)
        menu.addAction(act_about)

        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.quit_app)
        menu.addAction(act_quit)

        menu.aboutToShow.connect(self._sync_menu_checks)
        return menu

    def _sync_menu_checks(self):
        for val, act in self._menu_checks.get("size", {}).items():
            act.setChecked(abs(self.scale - val) < 0.01)
        act_auto = self._menu_checks.get("autostart")
        if act_auto is not None:
            act_auto.setChecked(autostart_on())

    def contextMenuEvent(self, event):
        logging.info("弹出右键菜单, 当前状态=%s, 位置=%s",
                     self.state, event.globalPos().toTuple())
        self.timer.stop()
        menu = self._build_menu()
        menu.exec(event.globalPos())
        self.timer.start(TICK_MS)

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.action_pet()
        elif reason == QSystemTrayIcon.Trigger:
            self.action_pet()

    def _toggle_autostart(self, checked):
        try:
            set_autostart(checked)
        except Exception as e:
            logging.exception("设置开机自启失败")
            QMessageBox.warning(self, "水豚噜噜", "设置开机自启失败：%s" % e)

    def show_about(self):
        QMessageBox.about(
            self, "关于水豚噜噜",
            "<h3>水豚噜噜桌宠 v0.1</h3>"
            "<p>一只住在你桌面上的水豚噜噜，<br>"
            "会发呆、眨眼、散步、打盹，还能被拎起来。</p>"
            "<p>左键拖动可以把噜噜挪到任何地方，<br>"
            "单击/右键有更多互动，更多玩法正在赶来的路上。</p>")

    def quit_app(self):
        self.cfg["scale"] = self.scale
        self.cfg["x"], self.cfg["y"] = self.x(), self.y()
        save_config(self.cfg)
        if self.tray:
            self.tray.hide()
        QApplication.quit()

    # ------------------------------------------------------------- 行为动作
    def action_pet(self):
        logging.info("摸头互动触发, 原状态=%s", self.state)
        self.last_interact = time.monotonic()
        if self.state == SLEEP:
            self.show_bubble(random.choice(WAKE_LINES))
        else:
            self.show_bubble(random.choice(HAPPY_LINES))
        self.enter_state(HAPPY)

    def show_bubble(self, text, seconds=2.2):
        self.bubble = {"text": text, "until": time.monotonic() + seconds}

    def set_scale(self, val):
        if abs(val - self.scale) < 0.01:
            return
        old_cx = self.x() + self.win_w / 2
        old_bottom = self.y() + self.win_h
        self.scale = val
        self._frame_cache.clear()
        self.win_w = int(270 * self.scale)
        self.win_h = int(430 * self.scale)
        self.setFixedSize(self.win_w, self.win_h)
        self.move(int(old_cx - self.win_w / 2), int(old_bottom - self.win_h))
        self.cfg["scale"] = self.scale
        self.update()

    def enter_state(self, state):
        self.state = state
        now = time.monotonic()
        self.state_since = now
        if state == IDLE:
            self.state_until = now + random.uniform(4, 9)
            self.next_blink = now + random.uniform(0.6, 2.5)
        elif state == WALK:
            self.state_until = now + random.uniform(6, 13)
            self.walk_phase = random.random() * 6
            if random.random() < 0.5:
                self.facing = -self.facing
            self._snap_to_ground()
            if random.random() < 0.4:
                self.show_bubble(random.choice(WALK_LINES), 1.8)
        elif state == HAPPY:
            self.state_until = now + 1.5
        elif state == SLEEP:
            self.zzz = []
            self.next_zzz = now + 0.5
        self.update()

    def current_screen_ground(self):
        """返回宠物当前所在屏幕的可用区（地面 = 底部）。"""
        center = self.geometry().center()
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        g = screen.availableGeometry()
        return g

    def _snap_to_ground(self):
        g = self.current_screen_ground()
        self.move(self.x(), g.bottom() - self.win_h + 12)

    # ------------------------------------------------------------- 鼠标交互
    def mousePressEvent(self, e):
        logging.info("鼠标按下 button=%s", e.button())
        if e.button() == Qt.LeftButton:
            self._press_pos = e.globalPosition().toPoint()
            self._press_win_pos = self.frameGeometry().topLeft()
            self._moved = False
            self.enter_state(DRAG)

    def mouseMoveEvent(self, e):
        if self._press_pos is None:
            return
        gp = e.globalPosition().toPoint()
        delta = gp - self._press_pos
        if delta.manhattanLength() > 5:
            self._moved = True
        if self._moved:
            ng = QApplication.primaryScreen().availableGeometry()
            nx = min(max(self._press_win_pos.x() + delta.x(), ng.left()),
                     ng.right() - self.win_w)
            ny = min(max(self._press_win_pos.y() + delta.y(), ng.top()),
                     ng.bottom() - self.win_h)
            self.move(nx, ny)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._press_pos is None:
            return
        self._press_pos = None
        self.last_interact = time.monotonic()
        if not self._moved:
            # 单击 = 摸头
            self.action_pet()
        else:
            # 松手落地：在屏幕下半区就放回地面，否则原地待着
            g = self.current_screen_ground()
            if self.y() > g.top() + g.height() * 0.55:
                self._snap_to_ground()
            self.enter_state(IDLE)

    # ------------------------------------------------------------- 帧推进
    def tick(self):
        now = time.monotonic()

        if self.state == IDLE:
            # 眨眼
            if now >= self.next_blink:
                self.blink_until = now + 0.16
                self.next_blink = now + random.uniform(2.2, 6.0)
                if random.random() < 0.18:   # 偶尔连眨两下
                    self.next_blink = now + 0.32
            # 偶尔做个表情
            if now > self.idle_face_until:
                self.idle_face = random.choices(
                    ["idle", "shy", "happy"], weights=[80, 10, 10])[0]
                self.idle_face_until = now + random.uniform(5, 12)
            # 状态流转
            if now - self.last_interact > SLEEP_AFTER:
                self.enter_state(SLEEP)
            elif now >= self.state_until:
                self.enter_state(WALK if random.random() < 0.7 else IDLE)

        elif self.state == WALK:
            dt = TICK_MS / 1000.0
            self.walk_phase += dt
            g = self.current_screen_ground()
            left = g.left() + 6
            right = g.right() - self.win_w - 6
            nx = self.x() + int(self.facing * WALK_SPEED * dt)
            if nx <= left:
                nx, self.facing = left, 1
            elif nx >= right:
                nx, self.facing = right, -1
            self.move(nx, g.bottom() - self.win_h + 12)
            if now >= self.state_until:
                self.enter_state(IDLE)

        elif self.state == HAPPY:
            if now >= self.state_until:
                self.enter_state(IDLE)

        elif self.state == SLEEP:
            # 冒 Zzz
            if now >= self.next_zzz:
                self.zzz.append({
                    "x": self.win_w * 0.56 + random.uniform(-8, 14) * self.scale,
                    "y": self.win_h * 0.47,
                    "born": now,
                })
                self.next_zzz = now + random.uniform(1.6, 2.6)
            self.zzz = [z for z in self.zzz if now - z["born"] < 3.2]

        # 气泡过期
        if self.bubble and now >= self.bubble["until"]:
            self.bubble = None

        self.update()

    # ------------------------------------------------------------- 帧渲染
    def _frame(self, name, h_logic, mirror=False):
        key = (name, round(h_logic), round(self.devicePixelRatio()),
               self.devicePixelRatioF(), mirror)
        cached = self._frame_cache.get(key)
        if cached is not None:
            return cached
        src = self.pix[name]
        dpr = self.devicePixelRatioF()
        w_logic = max(1, round(src.width() * h_logic / src.height()))
        frame = src.scaled(
            int(w_logic * dpr), int(h_logic * dpr),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if mirror:
            frame = frame.transformed(QTransform().scale(-1, 1))
        frame.setDevicePixelRatio(dpr)
        self._frame_cache[key] = frame
        return frame

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        now = time.monotonic()
        t = now - self.state_since

        name, h, mirror, rot, dy, sx, sy = self._current_visual(now, t)
        frame = self._frame(name, h, mirror)

        cx = self.win_w / 2
        bottom = self.win_h - 8 * self.scale

        fw = frame.width() / self.devicePixelRatioF()
        fh = frame.height() / self.devicePixelRatioF()

        p.save()
        p.translate(cx, bottom - dy)
        if rot:
            p.rotate(rot)
        p.scale(sx, sy)
        p.drawPixmap(QRectF(-fw / 2, -fh, fw, fh), frame,
                     QRectF(0, 0, frame.width(), frame.height()))
        p.restore()

        # 睡觉的 Zzz
        if self.state == SLEEP:
            for z in self.zzz:
                age = now - z["born"]
                alpha = max(0, 1 - age / 3.2)
                p.setPen(QColor(96, 122, 205, int(225 * alpha)))
                f = QFont("Microsoft YaHei", int(15 * self.scale + age * 3))
                f.setBold(True)
                p.setFont(f)
                p.drawText(QPointF(z["x"], z["y"] - age * 34 * self.scale), "Z")

        # 气泡
        if self.bubble:
            self._paint_bubble(p, self.bubble["text"])

        p.end()

    def _current_visual(self, now, t):
        """返回 (素材名, 逻辑高度, 镜像, 旋转°, 底部上移px, x缩放, y缩放)。"""
        name, h, mirror, rot, dy, sx, sy = FRAMES[IDLE], STAND_H, False, 0, 0, 1, 1

        if self.state == IDLE:
            blink = now < self.blink_until
            face = "blink" if blink else self.idle_face
            name = face
            breathe = math.sin(now * 2.1) * 0.015
            sx, sy = 1 - breathe * 0.6, 1 + breathe
        elif self.state == WALK:
            name = "walk1" if int(t * 5.5) % 2 == 0 else "walk2"
            mirror = self.facing < 0
            dy = abs(math.sin(t * 11)) * 5 * self.scale      # 走路颠簸
            sx = sy = 1.0
        elif self.state == DRAG:
            name = "drag"
            rot = math.sin(now * 9) * 3.5                    # 被拎着晃
            sy = 1.03
        elif self.state == HAPPY:
            name = "happy"
            if t < 0.45:                                      # 开心起跳
                dy = abs(math.sin(t / 0.45 * math.pi)) * 30 * self.scale
            sx = 1 + math.sin(t * 18) * 0.01
        elif self.state == SLEEP:
            name, h = "sleep", SLEEP_H
            sy = 1 + math.sin(now * 1.6) * 0.02              # 呼吸起伏

        h = h * self.scale
        return name, h, mirror, rot, dy, sx, sy

    def _paint_bubble(self, p, text):
        font = QFont("Microsoft YaHei", int(11 * self.scale))
        p.setFont(font)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        pad_x, pad_y = 12 * self.scale, 7 * self.scale
        bw = tw + pad_x * 2
        bh = th + pad_y * 2
        bx = self.win_w / 2 - bw / 2
        by = 10 * self.scale

        rect = QRectF(bx, by, bw, bh)
        p.setPen(QColor(255, 255, 255))
        p.setBrush(QColor(255, 255, 255, 235))
        p.drawRoundedRect(rect, 10 * self.scale, 10 * self.scale)
        # 小三角
        tri = [
            QPointF(self.win_w / 2 - 7 * self.scale, by + bh),
            QPointF(self.win_w / 2 + 7 * self.scale, by + bh),
            QPointF(self.win_w / 2, by + bh + 9 * self.scale),
        ]
        p.drawPolygon(tri)
        p.setPen(QColor(80, 60, 40))
        p.drawText(QRectF(bx, by + pad_y - fm.descent() / 2, bw, th),
                   Qt.AlignCenter, text)


# ---------------------------------------------------------------- main
def main():
    # pythonw 下没有控制台，未捕获异常写入日志
    def _excepthook(exc_type, exc, tb):
        logging.error("未捕获异常", exc_info=(exc_type, exc, tb))
    sys.excepthook = _excepthook

    # 单实例锁，避免重复多开
    shared = QSharedMemory("LuluPet_single_instance_lock")
    if not shared.create(1):
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # 桌宠靠托盘/菜单退出

    cfg = load_config()
    win = PetWindow(cfg)
    win.show()
    logging.info("水豚噜噜启动成功")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
