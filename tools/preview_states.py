# -*- coding: utf-8 -*-
"""开发验证用：渲染桌宠各状态截图，输出到 assets/raw/_preview_<state>.png"""
import os
import sys
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QApplication

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import lulu_pet

OUT = os.path.join(ROOT, "assets", "raw")


def grab_on_wallpaper(win, name):
    """把桌宠合成到深色壁纸色背景上，检查透明边缘与白边。"""
    shot = win.grab()
    from PySide6.QtGui import QPixmap
    canvas = QPixmap(shot.size())
    canvas.fill(QColor(58, 70, 88))
    p = QPainter(canvas)
    p.drawPixmap(0, 0, shot)
    p.end()
    canvas.save(os.path.join(OUT, f"_preview_{name}.png"))


def main():
    app = QApplication(sys.argv)
    win = lulu_pet.PetWindow({"scale": 1.0})
    win.show()

    states = [
        ("idle",  lambda: win.enter_state(lulu_pet.IDLE)),
        ("walk",  lambda: win.enter_state(lulu_pet.WALK)),
        ("drag",  lambda: win.enter_state(lulu_pet.DRAG)),
        ("happy", lambda: (win.show_bubble("噜噜~"), win.enter_state(lulu_pet.HAPPY))),
        ("sleep", lambda: win.enter_state(lulu_pet.SLEEP)),
    ]
    idx = {"i": 0}

    def step():
        if idx["i"] >= len(states):
            app.quit()
            return
        name, enter = states[idx["i"]]
        enter()
        # sleep 状态等 Zzz 出现
        delay = 2600 if name == "sleep" else 350

        def shoot():
            grab_on_wallpaper(win, name)
            idx["i"] += 1
            QTimer.singleShot(150, step)
        QTimer.singleShot(delay, shoot)

    QTimer.singleShot(500, step)
    app.exec()
    print("previews saved ->", OUT)


if __name__ == "__main__":
    main()
