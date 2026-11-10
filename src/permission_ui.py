"""界面权限可见性：按登录用户的权限项统一控制「按钮 / 页面 / 窗口 / 内容」。

用法：
    1) 创建控件后调用 ``bind(widget, perm_key)`` 打上权限标记；
    2) 权限刷新入口调用 ``apply_permissions(root, can)``，其中
       ``can(perm_key) -> bool`` 由 UserManager.can 提供。

一次递归扫描即可覆盖整棵控件树（含 QStackedWidget 内的生产 / 调试页面），
新增功能只需在控件创建处 bind 一次，无需改动刷新逻辑。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QStackedWidget, QTabWidget

PERMISSION_ATTR = "perm_key"


def bind(widget: QWidget | None, perm_key: str):
    """把控件绑定到某个权限项；无权限时该控件整体隐藏。"""
    if widget is not None:
        widget.setProperty(PERMISSION_ATTR, str(perm_key))
    return widget


def perm_key_of(widget: QWidget) -> str | None:
    v = widget.property(PERMISSION_ATTR)
    return str(v) if v else None


def bound_widgets(root: QWidget):
    """返回所有带权限标记的控件（含 root 自身）。"""
    out = []
    if perm_key_of(root):
        out.append(root)
    out.extend(w for w in root.findChildren(QWidget) if perm_key_of(w))
    return out


def apply_permissions(root: QWidget, can) -> dict:
    """整树刷新显隐，返回 {权限项: 是否有权限}，供回归断言使用。

    - 带标记的控件按 ``can(perm_key)`` 显隐；
    - QTabWidget 的页必须用 setTabVisible 控制，不能用 setVisible（Qt 内部管理）；
    - QStackedWidget 的页面本身不做显隐（由 switch_page 硬拦截进入），
      但会递归刷新**所有**页面的内部控件，切换页面时无需再手动刷新；
    - 幂等：同一权限反复刷新结果一致，权限被撤销 / 重新授予都能正确恢复。
    """
    state = {}

    def allowed(key):
        if key not in state:
            # 支持 ``父权限+子权限`` 组合：两级都授权才显示。
            # 用于「检测列表设置」及其 7 个细分操作这类父子层级。
            state[key] = all(bool(can(part)) for part in key.split("+") if part)
        return state[key]

    # QTabWidget 的页由 tabBar 管理，收集后跳过普通 setVisible
    tab_pages = set()
    for tab in root.findChildren(QTabWidget):
        for i in range(tab.count()):
            tab_pages.add(id(tab.widget(i)))
    for tab in root.findChildren(QTabWidget):
        for i in range(tab.count()):
            page_key = perm_key_of(tab.widget(i))
            if page_key:
                tab.setTabVisible(i, allowed(page_key))

    def walk(w):
        key = perm_key_of(w)
        if key and id(w) not in tab_pages:
            w.setVisible(allowed(key))
        for child in w.findChildren(
                QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            if isinstance(child, QStackedWidget):
                # 页面本身不显隐，但内部控件（工具条 / 页签 / 按钮）全部刷新
                for i in range(child.count()):
                    page = child.widget(i)
                    if page is not None:
                        walk(page)
                continue
            walk(child)

    walk(root)
    return state
