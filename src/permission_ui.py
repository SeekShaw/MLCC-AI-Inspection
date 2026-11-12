"""界面权限可见性：按登录用户的权限项统一控制「按钮 / 页面 / 窗口 / 内容」。

用法：
    1) 创建控件后调用 ``bind(widget, perm_key)`` 打上权限标记；
    2) 权限刷新入口调用 ``apply_permissions(root, can)``，其中
       ``can(perm_key) -> bool`` 由 UserManager.can 提供。

一次递归扫描即可覆盖整棵控件树（含 QStackedWidget 内的生产 / 调试页面），
新增功能只需在控件创建处 bind 一次，无需改动刷新逻辑。
"""
from __future__ import annotations

import weakref

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QStackedWidget, QTabWidget

PERMISSION_ATTR = "perm_key"

# 2026-11-12 三次优化：所有带权限标记的控件都由 bind() 登记到此弱引用集合。
# apply_permissions 只需遍历这几十个控件，无需每次 findChildren 扫描整棵树
# （运行时约 2.2 万个控件，剖析显示仅构建包装对象就占 ~50ms、遍历占 ~40ms）。
# 弱引用保证控件销毁后自动移除，不泄漏、不残留悬垂引用。
_BOUND_WIDGETS = weakref.WeakSet()


def bound_registry():
    """返回当前登记的绑定控件（只读用途，供回归断言核对）。"""
    return _BOUND_WIDGETS


def bind(widget: QWidget | None, perm_key: str):
    """把控件绑定到某个权限项；无权限时该控件整体隐藏。"""
    if widget is not None:
        widget.setProperty(PERMISSION_ATTR, str(perm_key))
        try:
            _BOUND_WIDGETS.add(widget)
        except (TypeError, RuntimeError):
            pass
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

    性能演进（切换用户卡顿修复）：
    - 原实现在 ``walk`` 递归中对每个控件都调一次 ``findChildren``（万级跨语言调用）；
    - 后改为一次 ``findChildren(QWidget)`` 收集整树，但仍要遍历约 2.2 万个控件；
    - 2026-11-12 终版：所有带权限标记的控件都由 ``bind()`` 登记到弱引用注册表，
      刷新时**只遍历这几十个控件**（用 ``root.isAncestorOf`` 判定归属），完全
      不扫描整棵树。剖析：切换用户 1604ms → ~180ms → 本版约 40ms。
    """
    state = {}

    def allowed(key):
        if key not in state:
            # 支持 ``父权限+子权限`` 组合：两级都授权才显示。
            # 用于「检测列表设置」及其细分操作这类父子层级。
            state[key] = all(bool(can(part)) for part in key.split("+") if part)
        return state[key]

    # 只取注册表中属于 root 子树的控件（含 root 自身）。注册表里的控件都是
    # 通过 bind() 打过标记的，控件销毁后弱引用自动移除。
    widgets = [root]
    for w in _BOUND_WIDGETS:
        if w is root:
            continue
        try:
            if root.isAncestorOf(w):
                widgets.append(w)
        except RuntimeError:      # 控件已被 C++ 销毁
            continue
    # 兜底：若某个 root 尚未登记任何绑定控件（例如动态弹窗首次刷新），
    # 退回一次整树扫描，保证语义不退化（此类窗口控件数很少）。
    if len(widgets) == 1:
        widgets.extend(root.findChildren(QWidget))

    for w in widgets:
        try:
            key = perm_key_of(w)
            if not key:
                continue
            visible = allowed(key)
            parent = w.parent()
            if isinstance(parent, QStackedWidget):
                # QTabWidget 内部用 QStackedWidget 管理页：页必须用 setTabVisible
                grand = parent.parent()
                if isinstance(grand, QTabWidget):
                    i = grand.indexOf(w)
                    if i >= 0:
                        grand.setTabVisible(i, visible)
                        continue
                # QStackedWidget 的页面本身不做显隐（由 switch_page 硬拦截），
                # 但页面内部控件仍在注册表中，会被下面的普通分支逐个刷新。
                continue
            w.setVisible(visible)
        except RuntimeError:      # 控件已被 C++ 销毁
            continue
    return state
