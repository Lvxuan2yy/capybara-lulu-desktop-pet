# -*- coding: utf-8 -*-
"""开发验证用：离屏检查右键菜单结构、开机自启注册表读写、大小切换、全状态切换。"""
import os
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import lulu_pet

results = []


def main():
    app = QApplication(sys.argv)
    win = lulu_pet.PetWindow({"scale": 1.0})

    # 1) 菜单结构
    menu = win._build_menu()
    texts = []
    def walk(m, depth=0):
        for a in m.actions():
            texts.append("  " * depth + (a.text() or "(子菜单)") +
                         (" [可勾选]" if a.isCheckable() else "") +
                         (" [勾选]" if a.isCheckable() and a.isChecked() else ""))
            if a.menu():
                walk(a.menu(), depth + 1)
    walk(menu)
    results.append("菜单结构:\n" + "\n".join(texts))

    # 2) 全状态切换
    for st in [lulu_pet.IDLE, lulu_pet.WALK, lulu_pet.HAPPY,
               lulu_pet.SLEEP, lulu_pet.DRAG, lulu_pet.IDLE]:
        win.enter_state(st)
    results.append("全状态切换: OK")

    # 3) 三档大小
    for v in [0.8, 1.0, 1.25, 1.0]:
        win.set_scale(v)
    results.append("大小切换: OK, 最终 scale=%s, 窗口=%sx%s" %
                   (win.scale, win.win_w, win.win_h))

    # 4) 气泡
    win.show_bubble("测试气泡")
    results.append("气泡: OK")

    # 5) 开机自启注册表读写（测完还原为关闭）
    if lulu_pet.autostart_supported():
        before = lulu_pet.autostart_on()
        lulu_pet.set_autostart(True)
        on = lulu_pet.autostart_on()
        lulu_pet.set_autostart(False)
        off = not lulu_pet.autostart_on()
        lulu_pet.set_autostart(before)
        results.append(f"开机自启: 写入={on} 关闭={off} 已还原({before})")
    else:
        results.append("开机自启: 当前系统不支持")

    # 6) 配置保存
    lulu_pet.save_config({"scale": 1.0, "x": 100, "y": 100})
    cfg = lulu_pet.load_config()
    results.append(f"配置读写: {cfg}")

    print("\n\n".join(results))
    QTimer.singleShot(200, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
