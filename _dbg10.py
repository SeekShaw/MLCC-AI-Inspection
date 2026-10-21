# -*- coding: utf-8 -*-
"""临时诊断：真实主程序 + 切到调试页，看放大窗实际定位。"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
import app as appmod

win = appmod.MainWindow()
win.setMinimumSize(0, 0)
win.showMaximized()
for _ in range(15):
    app.processEvents()

dv = win.debug_views[0]
win.stack.setCurrentWidget(dv)      # 真正切到调试页（激活其布局）
for _ in range(15):
    app.processEvents()

page = dv._flow_page
tabs = dv._target_tabs
scr = QGuiApplication.primaryScreen()
print("屏幕可用:", scr.availableGeometry(), "DPR:", scr.devicePixelRatio())
print("主窗:", win.width(), "x", win.height(), "几何:", win.geometry())


def gy(w):
    p = w.mapToGlobal(w.rect().topLeft())
    return p.x(), p.y()


print("header 下缘:", win._header_frame.mapToGlobal(
    win._header_frame.rect().bottomLeft()).y())
print("tabs top:", gy(tabs), "| card top:", gy(tabs.parentWidget()))
print("page top:", gy(page), "| canvas:", page.canvas.width(), "x",
      page.canvas.height(), "at", gy(page.canvas))

page._open_dialog()
for _ in range(15):
    app.processEvents()
dlg = page._dlg
print("dlg:", dlg.x(), dlg.y(), dlg.width(), "x", dlg.height(),
      "| 页底:", page.mapToGlobal(page.rect().bottomLeft()).y())
print("上次定位诊断:", getattr(page, "_last_geo_dbg", None))
