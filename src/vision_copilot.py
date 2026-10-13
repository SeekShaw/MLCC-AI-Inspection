# -*- coding: utf-8 -*-
"""Vision Copilot：工业视觉智能助手（多模态对话 + 服务配置）。

- CopilotWorker：QThread 内用 urllib 调用 OpenAI 兼容 /chat/completions，
  支持图片（base64 data URL）输入；沙箱 TLS 吊销拦截用不校验证书上下文绕开。
- VisionCopilotDialog：主对话窗（欢迎语 / 建议卡片 / 快捷指令 / 可粘贴拖入图片的输入框）。
- CopilotConfigDialog：服务配置窗（服务商 / API Key / Base URL / 视觉模型 / MCP 协同）。
"""
from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.request

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QImage, QPixmap, QGuiApplication, QDesktopServices, QColor
from PyQt6.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QScrollArea, QTextEdit, QLineEdit, QComboBox,
    QSpinBox, QMessageBox, QSizePolicy, QFileDialog,
)
from PyQt6.QtCore import QUrl

from styles import COLORS
from nav_dialogs import ToggleSwitch
import copilot_config

# 单张图片发送前的最长边（像素），过大则等比缩小，控制请求体大小
_IMG_MAX_SIDE = 1280


# ---------------------------------------------------------------------------
# 网络：OpenAI 兼容调用
# ---------------------------------------------------------------------------
def _ssl_ctx():
    """沙箱会拦截 GitHub/各家 API 的 TLS 吊销检查，用不校验证书的上下文绕开。"""
    try:
        return ssl._create_unverified_context()
    except Exception:
        return None


def _image_to_data_url(src, max_side=_IMG_MAX_SIDE) -> str:
    """把 QImage / QPixmap / 文件路径 转成 base64 data URL（JPEG，等比缩小）。"""
    if isinstance(src, str):
        img = QImage(src)
    elif isinstance(src, QPixmap):
        img = src.toImage()
    elif isinstance(src, QImage):
        img = src
    else:
        return ""
    if img.isNull():
        return ""
    w, h = img.width(), img.height()
    if max(w, h) > max_side:
        sc = max_side / float(max(w, h))
        img = img.scaled(int(w * sc), int(h * sc),
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    buf = bytearray()
    # 用 QBuffer 需要 QtCore；这里退而用 PIL 不可用，改用 QPixmap.save 到临时 QBuffer
    from PyQt6.QtCore import QBuffer, QIODevice
    qbuf = QBuffer()
    qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(qbuf, "JPEG", 82)
    qbuf.close()
    data = bytes(qbuf.data())
    del buf
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


def _pix_from(src, max_side=96) -> QPixmap:
    """生成缩略图 QPixmap。"""
    if isinstance(src, str):
        pm = QPixmap(src)
    elif isinstance(src, QPixmap):
        pm = src
    elif isinstance(src, QImage):
        pm = QPixmap.fromImage(src)
    else:
        return QPixmap()
    if pm.isNull():
        return QPixmap()
    if max(pm.width(), pm.height()) > max_side:
        pm = pm.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    return pm


class CopilotWorker(QThread):
    """在后台线程执行一次多模态对话请求。"""
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, cfg, messages, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._messages = messages

    def run(self):
        try:
            base = copilot_config.effective_base_url(self._cfg).rstrip("/")
            model = copilot_config.effective_model(self._cfg)
            if not base or not model:
                self.failed.emit("Base URL 或视觉模型为空，请先在「服务配置」中设置。")
                return
            url = base + "/chat/completions"
            headers = {"Content-Type": "application/json"}
            key = (self._cfg.get("api_key") or "").strip()
            if key:
                headers["Authorization"] = "Bearer " + key
            body = {"model": model, "messages": self._messages,
                    "temperature": 0.3, "stream": False}
            req = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"),
                headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=180, context=_ssl_ctx()) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            text = payload["choices"][0]["message"]["content"]
            if not isinstance(text, str):
                text = json.dumps(text, ensure_ascii=False)
            self.done.emit(text)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8")
            except Exception:
                detail = ""
            self.failed.emit(f"HTTP {e.code}：{detail[:400]}")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class ProbeWorker(QThread):
    """连通性 / 拉取模型列表（GET {base}/models）。"""
    done = pyqtSignal(list)     # 模型 id 列表
    failed = pyqtSignal(str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self._cfg = cfg

    def run(self):
        try:
            base = copilot_config.effective_base_url(self._cfg).rstrip("/")
            if not base:
                self.failed.emit("Base URL 为空。")
                return
            headers = {}
            key = (self._cfg.get("api_key") or "").strip()
            if key:
                headers["Authorization"] = "Bearer " + key
            req = urllib.request.Request(base + "/models", headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx()) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            ids = [m.get("id") for m in payload.get("data", []) if m.get("id")]
            self.done.emit(ids)
        except urllib.error.HTTPError as e:
            self.failed.emit(f"HTTP {e.code}")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


# ---------------------------------------------------------------------------
# 小组件
# ---------------------------------------------------------------------------
class _InputEdit(QTextEdit):
    """多行输入框：Enter 发送、Shift+Enter 换行、Ctrl+V 有图则粘贴为附件。"""

    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self._dlg = dialog
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet(
            f"QTextEdit {{ background-color: {COLORS['bg_dark']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 8px; "
            f"padding: 8px; color: {COLORS['text_primary']}; font-size: 13px; }}")

    def keyPressEvent(self, e):
        mods = e.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier and e.key() == Qt.Key.Key_V:
            cb = QGuiApplication.clipboard()
            md = cb.mimeData()
            if md is not None and md.hasImage():
                self._dlg.attach_image(cb.pixmap())
                e.accept()
                return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (mods & Qt.KeyboardModifier.ShiftModifier):
            self._dlg._on_send()
            e.accept()
            return
        super().keyPressEvent(e)


def _escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _render_markup(text: str) -> str:
    """极简渲染：转义 HTML + 换行转 <br>；```代码块``` 用等宽底色。"""
    parts = text.split("```")
    out = []
    for i, seg in enumerate(parts):
        if i % 2 == 1:  # 代码块
            out.append("<pre style='background:%s;color:%s;padding:6px;border-radius:6px;"
                       "white-space:pre-wrap;margin:4px 0;'>%s</pre>"
                       % (COLORS["bg_dark"], COLORS["text_primary"], _escape(seg.strip())))
        else:
            out.append(_escape(seg).replace("\n", "<br>"))
    return "".join(out)


def _btn_style(bg=None, fg=None, border=None, size=12, pad="6px 14px", bold=False):
    bg = bg if bg is not None else COLORS["bg_card"]
    fg = fg if fg is not None else COLORS["text_primary"]
    bd = f"border: 1px solid {border};" if border else "border: none;"
    w = "font-weight: bold;" if bold else ""
    return (f"QPushButton {{ background-color: {bg}; color: {fg}; {bd} "
            f"border-radius: 6px; padding: {pad}; font-size: {size}px; {w} }}"
            f"QPushButton:hover {{ background-color: {COLORS['border']}; }}")


def _card_style(selected: bool) -> str:
    if selected:
        return (f"QFrame {{ background-color: {COLORS['bg_card']}; "
                f"border: 1.5px solid {COLORS['accent_blue']}; border-radius: 8px; }}")
    return (f"QFrame {{ background-color: {COLORS['bg_panel']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 8px; }}")


# ---------------------------------------------------------------------------
# 主对话窗
# ---------------------------------------------------------------------------
SUGGESTIONS = [
    ("✦", "帮我搭建一个工件圆孔直径测量流程"),
    ("🧭", "为什么当前节点报错了？帮我排查原因"),
    ("👁", "截取窗图画面，分析表面划痕特征并推荐算子"),
]

QUICK_ACTIONS = [
    ("✦ 故障诊断", COLORS["accent_blue"], "white"),
    ("▶ 执行全流程", COLORS["accent_green"], "white"),
    ("🧩 缺陷检测模板", COLORS["accent_blue"], "white"),
    # 「算法调优」紧邻「截取窗图」左侧：先填调优指令，再一键截图带入上下文
    ("🧠 算法调优", COLORS["accent_blue"], "white"),
    ("🖼 截取窗图", COLORS["bg_card"], COLORS["text_primary"]),
]


class VisionCopilotDialog(QDialog):
    """工业视觉智能助手对话窗。"""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._cfg = copilot_config.load_cfg()
        self._pending = []          # [{"data_url": str, "pix": QPixmap}]
        self._worker = None
        self._thinking_item = None
        self.setWindowTitle("Vision Copilot")
        self.resize(600, 780)
        self.setMinimumSize(520, 620)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")
        self.setAcceptDrops(True)
        self._build()
        self._refresh_header()

    # ---------------- UI 构建 ----------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_topbar())

        # 中间堆叠：欢迎页 / 对话区
        self._stack_host = QWidget()
        sh = QVBoxLayout(self._stack_host)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(0)
        self._welcome = self._build_welcome()
        sh.addWidget(self._welcome)

        self._chat_scroll = QScrollArea()
        self._chat_scroll.setWidgetResizable(True)
        self._chat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._chat_scroll.setStyleSheet("background: transparent;")
        self._chat_inner = QWidget()
        self._chat_lay = QVBoxLayout(self._chat_inner)
        self._chat_lay.setContentsMargins(14, 14, 14, 14)
        self._chat_lay.setSpacing(10)
        self._chat_lay.addStretch(1)
        self._chat_scroll.setWidget(self._chat_inner)
        self._chat_scroll.hide()
        sh.addWidget(self._chat_scroll, 1)
        root.addWidget(self._stack_host, 1)

        root.addWidget(self._build_attach_strip())
        root.addWidget(self._build_quick_row())
        root.addWidget(self._build_input())

    def _build_topbar(self):
        bar = QFrame()
        bar.setFixedHeight(48)
        bar.setStyleSheet(f"QFrame {{ background-color: {COLORS['bg_panel']}; }}")
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 0, 12, 0)
        h.setSpacing(8)
        logo = QLabel("✦")
        logo.setStyleSheet(f"color: {COLORS['accent_blue']}; font-size: 20px;")
        title = QLabel("Vision Copilot")
        title.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 15px; font-weight: bold;")
        h.addWidget(logo)
        h.addWidget(title)
        self._mcp_status = QLabel("● MCP: 端口 8765 运行中")
        self._mcp_status.setStyleSheet(f"color: {COLORS['accent_green']}; font-size: 11px;")
        h.addWidget(self._mcp_status)
        self._model_chip = QLabel(copilot_config.effective_model(self._cfg))
        self._model_chip.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px; "
            f"background-color: {COLORS['bg_card']}; border-radius: 8px; padding: 2px 8px;")
        h.addWidget(self._model_chip)
        h.addStretch(1)
        cfg_btn = QPushButton("⚙ 服务配置")
        cfg_btn.setStyleSheet(_btn_style(COLORS["bg_card"], COLORS["text_primary"],
                                         COLORS["border"], 12, "5px 12px"))
        cfg_btn.clicked.connect(self._open_config)
        h.addWidget(cfg_btn)
        close_btn = QPushButton("✕")
        close_btn.setFixedWidth(34)
        close_btn.setStyleSheet(_btn_style(COLORS["bg_card"], COLORS["text_secondary"],
                                           COLORS["border"], 13, "4px 0px"))
        close_btn.clicked.connect(self.close)
        h.addWidget(close_btn)
        return bar

    def _build_welcome(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(28, 30, 28, 20)
        v.setSpacing(10)
        v.addStretch(1)
        logo = QLabel("✦")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(f"color: {COLORS['accent_blue']}; font-size: 52px;")
        v.addWidget(logo)
        t = QLabel("工业视觉智能助手")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 20px; font-weight: bold;")
        v.addWidget(t)
        sub = QLabel("基于多模态大模型、算子推荐、流程构建、缺陷诊断")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        v.addWidget(sub)
        v.addSpacing(14)
        for icon, text in SUGGESTIONS:
            card = QPushButton(f"  {icon}   {text}")
            card.setMinimumHeight(46)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setStyleSheet(_btn_style(COLORS["bg_card"], COLORS["text_primary"],
                                          COLORS["border"], 13, "10px 14px"))
            card.clicked.connect(lambda _=False, tx=text: self._use_suggestion(tx))
            v.addWidget(card)
        v.addSpacing(16)
        foot = QLabel("⚡ 原生算子执行 · 🔗 MCP 协议集成 · 👁 视觉多模态直传")
        foot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        foot.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        v.addWidget(foot)
        v.addStretch(1)
        return w

    def _build_attach_strip(self):
        self._attach_strip = QWidget()
        hl = QHBoxLayout(self._attach_strip)
        hl.setContentsMargins(14, 6, 14, 0)
        hl.setSpacing(8)
        hl.addStretch(1)
        self._attach_strip.hide()
        return self._attach_strip

    def _build_quick_row(self):
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(14, 8, 14, 4)
        hl.setSpacing(8)
        self._quick_btns = []
        for text, bg, fg in QUICK_ACTIONS:
            b = QPushButton(text)
            b.setMinimumHeight(30)
            b.setStyleSheet(_btn_style(bg, fg, None, 12, "5px 12px"))
            self._quick_btns.append(b)
            hl.addWidget(b)
        self._quick_btns[0].clicked.connect(lambda: self._use_quick("故障诊断"))
        self._quick_btns[1].clicked.connect(lambda: self._use_quick("执行全流程"))
        self._quick_btns[2].clicked.connect(lambda: self._use_quick("缺陷检测模板"))
        self._quick_btns[3].clicked.connect(lambda: self._use_quick("算法调优"))
        self._quick_btns[4].clicked.connect(self._capture_viewport)
        return row

    def _build_input(self):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 4, 14, 12)
        v.setSpacing(6)
        self._input = _InputEdit(self)
        self._input.setPlaceholderText("输入视觉需求或指令，可 Ctrl+V 粘贴 / 拖入图片...")
        self._input.setFixedHeight(84)
        v.addWidget(self._input)
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        img_btn = QPushButton("🖼")
        img_btn.setFixedSize(34, 30)
        img_btn.setToolTip("添加图片")
        img_btn.setStyleSheet(_btn_style(COLORS["bg_card"], COLORS["text_primary"],
                                         COLORS["border"], 14, "2px 0px"))
        img_btn.clicked.connect(self._pick_image)
        bottom.addWidget(img_btn)
        sp_btn = QPushButton("✦")
        sp_btn.setFixedSize(34, 30)
        sp_btn.setToolTip("AI 指令")
        sp_btn.setStyleSheet(_btn_style(COLORS["bg_card"], COLORS["accent_blue"],
                                        COLORS["border"], 14, "2px 0px"))
        bottom.addWidget(sp_btn)
        hint = QLabel("Enter 发送 · Shift+Enter 换行")
        hint.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        bottom.addWidget(hint)
        bottom.addStretch(1)
        self._send_btn = QPushButton("发送 ▶")
        self._send_btn.setMinimumHeight(32)
        self._send_btn.setStyleSheet(_btn_style(COLORS["accent_blue"], "white",
                                                None, 13, "6px 18px", bold=True))
        self._send_btn.clicked.connect(self._on_send)
        bottom.addWidget(self._send_btn)
        v.addLayout(bottom)
        return box

    # ---------------- 头部 / 状态 ----------------
    def _refresh_header(self):
        try:
            self._model_chip.setText(copilot_config.effective_model(self._cfg) or "未配置模型")
        except Exception:
            pass

    # ---------------- 图片附件 ----------------
    def attach_image(self, src):
        data_url = _image_to_data_url(src)
        if not data_url:
            return
        self._pending.append({"data_url": data_url, "pix": _pix_from(src)})
        self._rebuild_attach_strip()

    def _rebuild_attach_strip(self):
        lay = self._attach_strip.layout()
        while lay.count() > 1:  # 保留末尾 stretch
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        for i, item in enumerate(self._pending):
            thumb = QLabel()
            thumb.setFixedSize(64, 64)
            thumb.setPixmap(item["pix"].scaled(60, 60, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
            thumb.setStyleSheet(f"border: 1px solid {COLORS['border']}; border-radius: 6px; "
                                f"background: {COLORS['bg_card']};")
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wrap = QWidget()
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(0, 0, 0, 0)
            wl.setSpacing(2)
            wl.addWidget(thumb)
            rm = QPushButton("移除")
            rm.setFixedHeight(20)
            rm.setStyleSheet(_btn_style(COLORS["bg_panel"], COLORS["text_secondary"],
                                        COLORS["border"], 10, "1px 6px"))
            rm.clicked.connect(lambda _=False, idx=i: self._remove_pending(idx))
            wl.addWidget(rm)
            lay.insertWidget(lay.count() - 1, wrap)
        self._attach_strip.setVisible(bool(self._pending))

    def _remove_pending(self, idx):
        if 0 <= idx < len(self._pending):
            self._pending.pop(idx)
            self._rebuild_attach_strip()

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if path:
            self.attach_image(path)

    # ---------------- 快捷指令 / 建议 ----------------
    def _use_suggestion(self, text):
        self._input.setPlainText(text)
        self._input.setFocus()

    def _use_quick(self, kind):
        prompts = {
            "故障诊断": "请基于当前检测配置做一次故障诊断：列出可能的失效环节、排查顺序与处置建议。",
            "执行全流程": "请给出从进料到判定剔除的完整检测流程建议，并标注每步关键参数。",
            "缺陷检测模板": "请给我一套 MLCC 常见缺陷（崩边、偏位、污渍、划痕等）的检测模板与推荐阈值。",
            "算法调优": ("请基于当前检测画面与配置做一次算法调优：对比实际检出效果与目标，"
                       "指出阈值/参数的差距，给出具体调整建议与预期收益；如有必要可结合截图分析。"),
        }
        self._input.setPlainText(prompts.get(kind, kind))
        self._input.setFocus()

    def _capture_viewport(self):
        app = self._app
        if app is None:
            return
        try:
            pm = app.grab()
        except Exception:
            pm = QPixmap()
        if pm is None or pm.isNull():
            QMessageBox.information(self, "提示", "未能截取主界面画面。")
            return
        self.attach_image(pm)
        self._input.setPlaceholderText("已附加上一步截图，可补充说明后发送...")

    # ---------------- 发送 / 渲染 ----------------
    def _on_send(self):
        text = self._input.toPlainText().strip()
        imgs = list(self._pending)
        if not text and not imgs:
            return
        if copilot_config.needs_key(self._cfg) and not (self._cfg.get("api_key") or "").strip():
            r = QMessageBox.question(self, "尚未配置 API Key",
                                     "当前服务商需要 API Key 才能调用。是否前往「服务配置」？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r == QMessageBox.StandardButton.Yes:
                self._open_config()
            return
        if self._worker is not None and self._worker.isRunning():
            return

        # 组装 OpenAI 兼容多模态消息
        content = []
        if text:
            content.append({"type": "text", "text": text})
        for it in imgs:
            content.append({"type": "image_url",
                            "image_url": {"url": it["data_url"]}})
        if not content:
            return
        user_content = content[0]["text"] if (len(content) == 1 and text) else content
        messages = [
            {"role": "system", "content": copilot_config.SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        self._add_user_bubble(text, [it["pix"] for it in imgs])
        self._input.clear()
        self._pending = []
        self._rebuild_attach_strip()
        self._input.setPlaceholderText("输入视觉需求或指令，可 Ctrl+V 粘贴 / 拖入图片...")
        self._show_chat()
        self._thinking_item = self._add_thinking()

        self._worker = CopilotWorker(self._cfg, messages, self)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, text):
        self._replace_thinking(text)
        self._worker = None

    def _on_failed(self, err):
        self._replace_thinking(f"⚠ 调用失败：{err}", error=True)
        self._worker = None

    def _show_chat(self):
        self._welcome.hide()
        self._chat_scroll.show()

    def _chat_add(self, widget):
        self._chat_lay.insertWidget(self._chat_lay.count() - 1, widget)

    def _add_user_bubble(self, text, pixmaps):
        wrap = QWidget()
        hl = QHBoxLayout(wrap)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addStretch(1)
        bubble = QFrame()
        bubble.setMaximumWidth(420)
        bubble.setStyleSheet(f"QFrame {{ background-color: {COLORS['accent_blue']}; "
                             f"border-radius: 10px; }}")
        bl = QVBoxLayout(bubble)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(6)
        if pixmaps:
            row = QHBoxLayout()
            row.setSpacing(4)
            for pm in pixmaps[:6]:
                lb = QLabel()
                lb.setFixedSize(64, 64)
                lb.setPixmap(pm.scaled(60, 60, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
                lb.setStyleSheet("border-radius: 6px; background: rgba(255,255,255,0.15);")
                lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
                row.addWidget(lb)
            row.addStretch(1)
            bl.addLayout(row)
        if text:
            lab = QLabel(_escape(text).replace("\n", "<br>"))
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lab.setStyleSheet("color: white; font-size: 13px; background: transparent;")
            bl.addWidget(lab)
        hl.addWidget(bubble)
        self._chat_add(wrap)
        self._scroll_bottom()

    def _add_thinking(self):
        wrap = QWidget()
        hl = QHBoxLayout(wrap)
        hl.setContentsMargins(0, 0, 0, 0)
        bubble = QFrame()
        bubble.setMaximumWidth(460)
        bubble.setStyleSheet(f"QFrame {{ background-color: {COLORS['bg_card']}; "
                             f"border: 1px solid {COLORS['border']}; border-radius: 10px; }}")
        bl = QVBoxLayout(bubble)
        bl.setContentsMargins(10, 8, 10, 8)
        lab = QLabel("⏳ 思考中…")
        lab.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px; background: transparent;")
        bl.addWidget(lab)
        hl.addWidget(bubble)
        hl.addStretch(1)
        self._chat_add(wrap)
        self._scroll_bottom()
        return bubble

    def _replace_thinking(self, text, error=False):
        if self._thinking_item is None:
            self._add_assistant_bubble(text, error=error)
            return
        old = self._thinking_item
        # 用助手气泡替换「思考中」气泡
        parent = old.parentWidget()
        idx = -1
        if parent is not None:
            lay = parent.layout()
            for i in range(lay.count()):
                if lay.itemAt(i).widget() is old:
                    idx = i
                    break
        self._add_assistant_bubble(text, error=error)
        if idx >= 0 and parent is not None:
            parent.layout().removeWidget(old)
        old.deleteLater()
        self._thinking_item = None

    def _add_assistant_bubble(self, text, error=False):
        wrap = QWidget()
        hl = QHBoxLayout(wrap)
        hl.setContentsMargins(0, 0, 0, 0)
        icon = QLabel("✦")
        icon.setFixedWidth(26)
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        icon.setStyleSheet(f"color: {COLORS['accent_blue']}; font-size: 16px; background: transparent;")
        hl.addWidget(icon)
        bubble = QFrame()
        bubble.setMaximumWidth(470)
        bubble.setStyleSheet(f"QFrame {{ background-color: {COLORS['bg_card']}; "
                             f"border: 1px solid {COLORS['border']}; border-radius: 10px; }}")
        bl = QVBoxLayout(bubble)
        bl.setContentsMargins(10, 8, 10, 8)
        lab = QLabel()
        lab.setWordWrap(True)
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        lab.setOpenExternalLinks(True)
        if error:
            lab.setText(f"<span style='color:{COLORS['accent_red']};font-size:13px;'>"
                        f"{_escape(text)}</span>")
        else:
            lab.setText(f"<div style='color:{COLORS['text_primary']};font-size:13px;'>"
                        f"{_render_markup(text)}</div>")
        lab.setStyleSheet("background: transparent;")
        bl.addWidget(lab)
        hl.addWidget(bubble)
        hl.addStretch(1)
        self._chat_add(wrap)
        self._scroll_bottom()

    def _scroll_bottom(self):
        try:
            bar = self._chat_scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
        except Exception:
            pass

    # ---------------- 配置 ----------------
    def _open_config(self):
        dlg = CopilotConfigDialog(self._cfg, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                self._cfg = dlg.result_cfg()
                copilot_config.save_cfg(self._cfg)
                self._refresh_header()
            except Exception:
                # 配置回读异常不应影响对话窗继续使用
                pass

    # ---------------- 拖放 ----------------
    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md is not None and (md.hasImage() or md.hasUrls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        if md is None:
            return
        if md.hasImage():
            self.attach_image(md.imageData())
        elif md.hasUrls():
            for u in md.urls():
                p = u.toLocalFile()
                if p:
                    self.attach_image(p)
        e.acceptProposedAction()


# ---------------------------------------------------------------------------
# 服务配置窗
# ---------------------------------------------------------------------------
class CopilotConfigDialog(QDialog):
    """AI & MCP 服务配置。"""

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self._cfg = dict(cfg or {})
        self._mcp = dict(self._cfg.get("mcp") or {})
        self._loading = True
        self._cards = {}
        self._key_visible = False
        self._probe = None
        # 「返回对话」（顶栏）与「完成并返回对话」（底部）均可能直接 accept 返回，
        # result_cfg() 需在无 _result 时兜底收集，避免 AttributeError 崩溃。
        self._result = None
        self.setWindowTitle("AI & MCP 服务配置")
        self.resize(620, 760)
        self.setMinimumSize(540, 640)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_dark']}; }}")
        self._build()
        self._load()
        self._loading = False

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_topbar())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        inner = QWidget()
        self._body = QVBoxLayout(inner)
        self._body.setContentsMargins(18, 14, 18, 14)
        self._body.setSpacing(14)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        self._build_providers()
        self._build_api()
        self._build_mcp()
        self._build_footer()

    def _build_topbar(self):
        bar = QFrame()
        bar.setFixedHeight(48)
        bar.setStyleSheet(f"QFrame {{ background-color: {COLORS['bg_panel']}; }}")
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 0, 12, 0)
        h.setSpacing(8)
        logo = QLabel("✦")
        logo.setStyleSheet(f"color: {COLORS['accent_blue']}; font-size: 18px;")
        title = QLabel("Vision Copilot")
        title.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 15px; font-weight: bold;")
        h.addWidget(logo)
        h.addWidget(title)
        h.addStretch(1)
        back = QPushButton("返回对话")
        back.setStyleSheet(_btn_style(COLORS["accent_blue"], "white", None, 12, "5px 14px"))
        # 与底部「完成并返回对话」同链路：先收集表单再 accept，避免直接 accept
        # 导致 result_cfg() 取不到 _result 而崩溃
        back.clicked.connect(self._on_done)
        h.addWidget(back)
        close_btn = QPushButton("✕")
        close_btn.setFixedWidth(34)
        close_btn.setStyleSheet(_btn_style(COLORS["bg_card"], COLORS["text_secondary"],
                                           COLORS["border"], 13, "4px 0px"))
        close_btn.clicked.connect(self.reject)
        h.addWidget(close_btn)
        return bar

    def _section(self, title):
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 15px; font-weight: bold;")
        self._body.addWidget(lbl)

    def _field_row(self, label, widget, label_w=150):
        row = QHBoxLayout()
        row.setSpacing(10)
        lb = QLabel(label)
        lb.setFixedWidth(label_w)
        lb.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lb.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 13px;")
        row.addWidget(lb)
        row.addWidget(widget, 1)
        return row

    def _line_edit(self, placeholder="", echo_password=False):
        le = QLineEdit()
        le.setMinimumHeight(32)
        le.setPlaceholderText(placeholder)
        if echo_password:
            le.setEchoMode(QLineEdit.EchoMode.Password)
        le.setStyleSheet(
            f"QLineEdit {{ background-color: {COLORS['bg_dark']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; "
            f"padding: 4px 10px; color: {COLORS['text_primary']}; font-size: 13px; }}")
        return le

    # ------- ① 服务商 -------
    def _build_providers(self):
        self._section("① 选择模型服务商")
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for i, pid in enumerate(copilot_config.PROVIDER_ORDER):
            p = copilot_config.PROVIDERS[pid]
            card = QPushButton()
            card.setMinimumHeight(64)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setStyleSheet(_card_style(False) +
                               "QPushButton { text-align: left; padding: 8px 10px; }")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(10, 6, 10, 6)
            cl.setSpacing(2)
            nm = QLabel(p["name"])
            nm.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: bold; background: transparent;")
            ds = QLabel(p["desc"])
            ds.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px; background: transparent;")
            cl.addWidget(nm)
            cl.addWidget(ds)
            card.clicked.connect(lambda _=False, k=pid: self._select_provider(k))
            self._cards[pid] = card
            r, c = divmod(i, 2)
            grid.addWidget(card, r, c)
        self._body.addWidget(grid_host)

    def _select_provider(self, pid):
        self._cfg["provider"] = pid
        self._refresh_provider_ui()

    def _refresh_provider_ui(self):
        pid = self._cfg.get("provider", "deepseek")
        p = copilot_config.PROVIDERS.get(pid, {})
        for k, card in self._cards.items():
            card.setStyleSheet(_card_style(k == pid) +
                               "QPushButton { text-align: left; padding: 8px 10px; }")
        # Base URL 占位符切到该服务商默认
        self._base_edit.setPlaceholderText(p.get("base_url", "") or "https://.../v1")
        # 模型下拉刷新
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        self._model_combo.addItems(p.get("models", []))
        self._model_combo.blockSignals(False)
        # Key 区显隐
        need = bool(p.get("needs_key", True))
        self._api_key_row.setVisible(need)
        self._key_link.setVisible(bool(p.get("key_url")))

    # ------- ② API Key -------
    def _build_api(self):
        self._section("② API Key 密钥（本地加密存储）")
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        self._key_edit = self._line_edit("sk-...", echo_password=True)
        hl.addWidget(self._key_edit, 1)
        self._key_eye = QPushButton("👁")
        self._key_eye.setFixedSize(38, 32)
        self._key_eye.setStyleSheet(_btn_style(COLORS["bg_card"], COLORS["text_primary"],
                                               COLORS["border"], 14, "2px 0px"))
        self._key_eye.clicked.connect(self._toggle_key_visible)
        hl.addWidget(self._key_eye)
        self._api_key_row = row
        self._body.addLayout(self._field_row("API Key", row))

        link_row = QHBoxLayout()
        link_row.setContentsMargins(150, 0, 0, 0)
        self._key_link = QPushButton("获取密钥入口 ↗")
        self._key_link.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {COLORS['accent_blue']}; "
            f"border: none; font-size: 12px; text-align: left; }}")
        self._key_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self._key_link.clicked.connect(self._open_key_url)
        link_row.addWidget(self._key_link)
        link_row.addStretch(1)
        self._body.addLayout(link_row)

        # ③ Base URL
        self._section("③ API 端点地址（Base URL）")
        self._base_edit = self._line_edit()
        self._body.addLayout(self._field_row("Base URL", self._base_edit))

        # 视觉大模型选择
        self._section("视觉大模型选择")
        model_row = QWidget()
        mh = QHBoxLayout(model_row)
        mh.setContentsMargins(0, 0, 0, 0)
        mh.setSpacing(8)
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setMinimumHeight(32)
        self._model_combo.setStyleSheet(
            f"QComboBox {{ background-color: {COLORS['bg_dark']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; "
            f"padding: 4px 10px; color: {COLORS['text_primary']}; font-size: 13px; }}"
            f"QComboBox QAbstractItemView {{ background-color: {COLORS['bg_dark']}; "
            f"color: {COLORS['text_primary']}; selection-background-color: {COLORS['accent_blue']}; }}")
        mh.addWidget(self._model_combo, 1)
        fetch_btn = QPushButton("获取模型")
        fetch_btn.setStyleSheet(_btn_style(COLORS["bg_card"], COLORS["text_primary"],
                                           COLORS["border"], 12, "6px 12px"))
        fetch_btn.clicked.connect(self._fetch_models)
        mh.addWidget(fetch_btn)
        self._body.addLayout(self._field_row("视觉模型", model_row))

        # 单轮最大工具调用轮次 + 视觉输入开关
        rounds_row = QWidget()
        rh = QHBoxLayout(rounds_row)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(8)
        self._rounds_spin = QSpinBox()
        self._rounds_spin.setRange(1, 200)
        self._rounds_spin.setMinimumHeight(32)
        self._rounds_spin.setStyleSheet(
            f"QSpinBox {{ background-color: {COLORS['bg_dark']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; "
            f"padding: 4px 10px; color: {COLORS['text_primary']}; font-size: 13px; }}")
        rh.addWidget(self._rounds_spin)
        self._force_vision_sw = ToggleSwitch(checked=False)
        rh.addWidget(self._force_vision_sw)
        fv = QLabel("视觉输入：中间态=自动；勾选=强制开")
        fv.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        rh.addWidget(fv)
        rh.addStretch(1)
        self._body.addLayout(self._field_row("单轮最大工具调用轮次", rounds_row))

    def _toggle_key_visible(self):
        self._key_visible = not self._key_visible
        self._key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if self._key_visible else QLineEdit.EchoMode.Password)
        self._key_eye.setText("🙈" if self._key_visible else "👁")

    def _open_key_url(self):
        p = copilot_config.PROVIDERS.get(self._cfg.get("provider", ""), {})
        url = p.get("key_url")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _fetch_models(self):
        cfg = self._collect()
        self._probe = ProbeWorker(cfg, self)
        self._probe.done.connect(self._on_models)
        self._probe.failed.connect(lambda e: QMessageBox.warning(self, "获取模型失败", e))
        self._probe.start()

    def _on_models(self, ids):
        if not ids:
            QMessageBox.information(self, "获取模型", "未返回可用模型列表。")
            return
        cur = self._model_combo.currentText()
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        self._model_combo.addItems(ids)
        if cur:
            self._model_combo.setCurrentText(cur)
        self._model_combo.blockSignals(False)
        QMessageBox.information(self, "获取模型", f"已拉取 {len(ids)} 个模型。")

    # ------- MCP 服务协同 -------
    def _build_mcp(self):
        box = QFrame()
        box.setStyleSheet(f"QFrame {{ background-color: {COLORS['bg_card']}; "
                          f"border: 1px solid {COLORS['border']}; border-radius: 8px; }}")
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)
        title = QLabel("⚙ 内置 MCP 服务协同")
        title.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 14px; font-weight: bold;")
        v.addWidget(title)

        self._mcp_auto_sw = ToggleSwitch(checked=True)
        v.addLayout(self._switch_row("随程序自启动 MCP Server", self._mcp_auto_sw))
        self._mcp_token_sw = ToggleSwitch(checked=True)
        v.addLayout(self._switch_row("强制 Token 鉴权（防止本机外部进程未授权调用）", self._mcp_token_sw))

        self._port_spin = QSpinBox()
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setMinimumHeight(30)
        self._port_spin.setStyleSheet(
            f"QSpinBox {{ background-color: {COLORS['bg_dark']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; "
            f"padding: 2px 8px; color: {COLORS['text_primary']}; }}")
        v.addLayout(self._field_row("监听端口（默认 8765）", self._port_spin, label_w=170))

        tok_row = QWidget()
        th = QHBoxLayout(tok_row)
        th.setContentsMargins(0, 0, 0, 0)
        th.setSpacing(8)
        self._token_edit = self._line_edit()
        self._token_edit.setReadOnly(True)
        th.addWidget(self._token_edit, 1)
        cp = QPushButton("复制")
        cp.setStyleSheet(_btn_style(COLORS["bg_card"], COLORS["text_primary"],
                                    COLORS["border"], 12, "6px 12px"))
        cp.clicked.connect(self._copy_token)
        th.addWidget(cp)
        regen = QPushButton("重新生成")
        regen.setStyleSheet(_btn_style(COLORS["bg_card"], COLORS["text_primary"],
                                       COLORS["border"], 12, "6px 12px"))
        regen.clicked.connect(self._regen_token)
        th.addWidget(regen)
        v.addLayout(self._field_row("MCP 访问令牌（Token）", tok_row, label_w=170))

        self._mcp_status = QLabel("MCP: 端口 8765 (运行中)")
        self._mcp_status.setStyleSheet(f"color: {COLORS['accent_green']}; font-size: 12px;")
        self._mcp_running = True
        self._mcp_toggle_btn = QPushButton("停止服务")
        self._mcp_toggle_btn.setStyleSheet(_btn_style(COLORS["bg_card"], COLORS["text_primary"],
                                                      COLORS["border"], 12, "6px 14px"))
        self._mcp_toggle_btn.clicked.connect(self._toggle_mcp)
        v.addLayout(self._field_row("服务状态", self._mcp_toggle_btn, label_w=170))
        v.addWidget(self._mcp_status)

        cur_cfg = QPushButton("复制 Cursor / IDE MCP 配置")
        cur_cfg.setStyleSheet(_btn_style(COLORS["bg_card"], COLORS["text_primary"],
                                         COLORS["border"], 12, "8px 14px"))
        cur_cfg.clicked.connect(self._copy_cursor_cfg)
        v.addWidget(cur_cfg)
        claude = QPushButton("复制 Claude Code CLI 挂载命令")
        claude.setStyleSheet(_btn_style(COLORS["bg_card"], COLORS["text_primary"],
                                        COLORS["border"], 12, "8px 14px"))
        claude.clicked.connect(self._copy_claude_cmd)
        v.addWidget(claude)
        self._body.addWidget(box)

    def _switch_row(self, name, sw, label_w=170):
        row = QHBoxLayout()
        row.setSpacing(10)
        lb = QLabel(name)
        lb.setFixedWidth(label_w)
        lb.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lb.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 13px;")
        row.addWidget(lb)
        row.addWidget(sw)
        row.addStretch(1)
        return row

    def _copy_token(self):
        QGuiApplication.clipboard().setText(self._token_edit.text())

    def _regen_token(self):
        import secrets as _secrets
        self._token_edit.setText(_secrets.token_hex(16))

    def _toggle_mcp(self):
        self._mcp_running = not self._mcp_running
        self._refresh_mcp_status()

    def _refresh_mcp_status(self):
        port = self._port_spin.value()
        if self._mcp_running:
            self._mcp_status.setText(f"MCP: 端口 {port} (运行中)")
            self._mcp_status.setStyleSheet(f"color: {COLORS['accent_green']}; font-size: 12px;")
            self._mcp_toggle_btn.setText("停止服务")
        else:
            self._mcp_status.setText(f"MCP: 端口 {port} (已停止)")
            self._mcp_status.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
            self._mcp_toggle_btn.setText("启动服务")

    def _copy_cursor_cfg(self):
        port = self._port_spin.value()
        token = self._token_edit.text()
        snippet = json.dumps({
            "mcpServers": {
                "vision-copilot": {
                    "url": f"http://127.0.0.1:{port}/mcp",
                    "headers": {"Authorization": f"Bearer {token}"}
                }
            }
        }, ensure_ascii=False, indent=2)
        QGuiApplication.clipboard().setText(snippet)
        QMessageBox.information(self, "已复制", "Cursor / IDE MCP 配置已复制到剪贴板。")

    def _copy_claude_cmd(self):
        port = self._port_spin.value()
        token = self._token_edit.text()
        cmd = (f"claude mcp add --transport http vision-copilot "
               f"http://127.0.0.1:{port}/mcp "
               f"--header \"Authorization: Bearer {token}\"")
        QGuiApplication.clipboard().setText(cmd)
        QMessageBox.information(self, "已复制", "Claude Code CLI 挂载命令已复制到剪贴板。")

    # ------- 底部：测试 + 完成 -------
    def _build_footer(self):
        self._test_btn = QPushButton("⚡ 测试当前配置连通性")
        self._test_btn.setMinimumHeight(38)
        self._test_btn.setStyleSheet(_btn_style(COLORS["bg_card"], COLORS["text_primary"],
                                                COLORS["border"], 13, "8px 16px"))
        self._test_btn.clicked.connect(self._test_conn)
        self._body.addWidget(self._test_btn)
        done = QPushButton("完成并返回对话")
        done.setMinimumHeight(40)
        done.setStyleSheet(_btn_style(COLORS["accent_blue"], "white", None, 14, "8px 16px", bold=True))
        done.clicked.connect(self._on_done)
        self._body.addWidget(done)
        self._body.addStretch(1)

    def _test_conn(self):
        cfg = self._collect()
        if not copilot_config.effective_base_url(cfg):
            QMessageBox.warning(self, "无法测试", "Base URL 为空。")
            return
        self._test_btn.setText("测试中…")
        self._test_btn.setEnabled(False)
        self._probe = ProbeWorker(cfg, self)
        self._probe.done.connect(self._on_test_done)
        self._probe.failed.connect(self._on_test_failed)
        self._probe.start()

    def _on_test_done(self, ids):
        self._test_btn.setText("⚡ 测试当前配置连通性")
        self._test_btn.setEnabled(True)
        QMessageBox.information(self, "连通性测试", f"连接成功，可用模型 {len(ids)} 个。")

    def _on_test_failed(self, err):
        self._test_btn.setText("⚡ 测试当前配置连通性")
        self._test_btn.setEnabled(True)
        QMessageBox.warning(self, "连通性测试失败", err)

    # ------- 读取 / 收集 / 保存 -------
    def _load(self):
        cfg = self._cfg
        self._refresh_provider_ui()
        self._key_edit.setText(cfg.get("api_key", "") or "")
        self._base_edit.setText(cfg.get("base_url", "") or "")
        model = cfg.get("vision_model", "") or ""
        if model:
            self._model_combo.setCurrentText(model)
        self._rounds_spin.setValue(int(cfg.get("max_rounds", 30) or 30))
        self._force_vision_sw.setChecked(bool(cfg.get("force_vision", False)))
        mcp = self._mcp
        self._mcp_auto_sw.setChecked(bool(mcp.get("autostart", True)))
        self._mcp_token_sw.setChecked(bool(mcp.get("force_token", True)))
        self._port_spin.setValue(int(mcp.get("port", 8765) or 8765))
        self._token_edit.setText(mcp.get("token", "") or "")
        self._refresh_mcp_status()

    def _collect(self) -> dict:
        model = self._model_combo.currentText().strip()
        return {
            "provider": self._cfg.get("provider", "deepseek"),
            "api_key": self._key_edit.text().strip(),
            "base_url": self._base_edit.text().strip(),
            "vision_model": model,
            "max_rounds": int(self._rounds_spin.value()),
            "force_vision": bool(self._force_vision_sw.isChecked()),
            "mcp": {
                "autostart": bool(self._mcp_auto_sw.isChecked()),
                "force_token": bool(self._mcp_token_sw.isChecked()),
                "port": int(self._port_spin.value()),
                "token": self._token_edit.text().strip(),
            },
        }

    def result_cfg(self) -> dict:
        # 顶栏「返回对话」直连 accept 时不会经过 _on_done，这里兜底收集当前表单值
        if self._result is None:
            self._result = self._collect()
        return self._result

    def _on_done(self):
        self._result = self._collect()
        self.accept()
