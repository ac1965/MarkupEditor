#!/usr/bin/env python3
"""Markup Editor (Python / tkinter 版)。

Windows / macOS / Linux で、Python 3.8 以上の標準ライブラリだけで動く
Markdown / Org エディタ。左で書くと右のプレビューにすぐ反映される。
ファイル名が .org なら Org として、それ以外は Markdown として解釈する
（Org は編集だけで、HTML への書き出しは Markdown のみ）。

    python markup_editor.py [ファイル.md | ファイル.org]
"""
import json
import re
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from html.parser import HTMLParser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from mdparser import export_html, md_to_html
from orgparser import org_to_html

APP = "Markup Editor"


def default_state_path():
    """下書き・テーマなどの保存先。どの OS でも、ホームの下の同じ相対パス。"""
    return Path.home() / ".markup-editor" / "state.json"


def legacy_state_path():
    """旧名（MD Editor）の保存先。引き継ぎの読み込みだけに使う。"""
    return Path.home() / ".md-editor" / "state.json"


SAMPLE = """# Markup Editor

左で書くと右にすぐ反映されます。

- **太字**、*斜体*、~~取り消し~~、`コード`
- [ ] チェックリスト
- [x] 完了した項目

| 項目 | 内容 |
|---|---|
| 保存 | Ctrl/⌘ + S |
| 開く | Ctrl/⌘ + O |

```js
console.log("hello");
```

> 引用もこのとおりです。
"""

THEMES = {
    "light": dict(bg="#ffffff", fg="#1f2328", sel="#b6d4fe", code="#eef0f3",
                  pre="#f4f6f8", link="#0b57d0", muted="#57606a",
                  rule="#c8ced6", panel="#f6f8fa"),
    "dark": dict(bg="#1e1f22", fg="#dfe1e5", sel="#2f4a73", code="#2b2d31",
                 pre="#26282c", link="#8ab4f8", muted="#9aa0a6",
                 rule="#4a4d52", panel="#2b2d31"),
}
HEADING_SCALE = {1: 1.8, 2: 1.5, 3: 1.3, 4: 1.15, 5: 1.05, 6: 1.0}
BULLETS = ["•", "◦", "▪"]
# 入力が止まってから描き直すまでの間隔（ms）。描画に時間がかかる文書ほど長くする
RENDER_MIN_MS, RENDER_MAX_MS = 120, 1500


class Renderer(HTMLParser):
    """mdparser / orgparser が出す HTML を、tkinter の Text に描く。

    パーサーは決まった範囲のタグしか出さないので、ここもその範囲だけを扱う
    （見出し、段落、強調、取り消し線、コード、リンク、リスト、引用、水平線、表、
    チェックボックス、画像の代替表示、Org の TODO とタグの <span>）。
    それ以外のタグは、中の文字だけを出す。
    """

    def __init__(self, app):
        super().__init__(convert_charrefs=True)
        self.app = app
        self.w = app.pv
        self.tail = ""
        self.bold = self.italic = self.code = self.strike = 0
        self.heading = self.pre = self.quote = self.muted = 0
        self.spans = []  # <span> ごとの種類（"bold" / "muted" / None）
        self.link = None
        self.lists = []
        self.table = None
        self.keep_inline = False

    # --- 書き込み -------------------------------------------------
    def write(self, text, extra=()):
        if not text:
            return
        self.keep_inline = False
        fixed = bool(self.pre or self.code)
        tags = list(extra)
        tags.append(self.app.font_tag(
            fixed, self.heading, self.bold > 0 or self.heading > 0,
            self.italic > 0))
        if self.strike:
            tags.append("strike")
        if self.code and not self.pre:
            tags.append("code")
        if self.pre:
            tags.append("pre")
        if self.link:
            tags.append(self.link)
        if self.quote or self.muted:
            tags.append("quote")
        tags.append(self.app.margin_tag(self.quote, len(self.lists)))
        self.w.insert("end", text, tuple(tags))
        self.tail = (self.tail + text)[-2:]

    def ensure_nl(self):
        if self.keep_inline:
            return
        if self.tail and not self.tail.endswith("\n"):
            self.write("\n")

    def ensure_blank(self):
        if not self.tail:
            return
        self.ensure_nl()
        if not self.tail.endswith("\n\n"):
            self.write("\n")

    # --- タグ -----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.table is not None:
            if tag == "tr":
                self.table["row"] = []
            elif tag in ("th", "td"):
                self.table["cell"] = []
                m = re.search(r"text-align:(\w+)", a.get("style") or "")
                self.table["align"] = m.group(1) if m else "left"
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.ensure_blank()
            self.heading = int(tag[1])
        elif tag == "p":
            if self.lists or self.quote:
                self.ensure_nl()
            else:
                self.ensure_blank()
            if self.quote and not self.lists:
                self.write("▍" * self.quote + " ")
        elif tag in ("strong", "b"):
            self.bold += 1
        elif tag in ("em", "i"):
            self.italic += 1
        elif tag in ("del", "s"):
            self.strike += 1
        elif tag == "code":
            self.code += 1
        elif tag == "span":  # Org の TODO キーワード（太字）とタグ（目立たない色）
            cls = (a.get("class") or "").split()
            kind = "bold" if "todo" in cls else "muted" if "tag" in cls else None
            self.spans.append(kind)
            self.bold += kind == "bold"
            self.muted += kind == "muted"
        elif tag == "pre":
            self.ensure_blank()
            self.pre += 1
        elif tag == "a":
            self.link = self.app.link_tag(a.get("href") or "")
        elif tag in ("ul", "ol"):
            if self.lists:
                self.ensure_nl()
            else:
                self.ensure_blank()
            try:
                start = int(a.get("start", "1"))
            except ValueError:
                start = 1
            self.lists.append([tag == "ol", start - 1])
        elif tag == "li":
            self.ensure_nl()
            item = self.lists[-1] if self.lists else [False, 0]
            item[1] += 1
            depth = max(len(self.lists), 1)
            marker = ("%d. " % item[1] if item[0]
                      else BULLETS[min(depth - 1, 2)] + " ")
            self.write(marker)
            self.keep_inline = True
        elif tag == "blockquote":
            if self.quote:
                self.ensure_nl()
            else:
                self.ensure_blank()
            self.quote += 1
        elif tag == "hr":
            self.ensure_blank()
            reg = self.app.fonts[self.app.font_tag(False, 0, False, False)]
            avail = self.w.winfo_width() - 48  # 余白とスクロールバー分
            n = avail // max(1, reg.measure("─")) if avail > 0 else 40
            self.write("─" * max(10, n), ("hr",))
            self.write("\n")
        elif tag == "br":
            self.write("\n")
        elif tag == "input":
            self.write("☑ " if "checked" in a else "☐ ")
        elif tag == "img":
            self.write("[画像: %s] " % (a.get("alt") or ""))
        elif tag == "table":
            self.ensure_blank()
            self.table = dict(rows=[], row=None, cell=None, align="left")

    def handle_endtag(self, tag):
        if self.table is not None:
            t = self.table
            if tag in ("th", "td") and t["cell"] is not None:
                t["row"].append(("".join(t["cell"]).strip(), t["align"]))
                t["cell"] = None
            elif tag == "tr" and t["row"] is not None:
                t["rows"].append(t["row"])
                t["row"] = None
            elif tag == "table":
                self.table = None
                self.draw_table(t["rows"])
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.ensure_nl()
            self.heading = 0
        elif tag == "p":
            self.ensure_nl()
        elif tag in ("strong", "b"):
            self.bold = max(0, self.bold - 1)
        elif tag in ("em", "i"):
            self.italic = max(0, self.italic - 1)
        elif tag in ("del", "s"):
            self.strike = max(0, self.strike - 1)
        elif tag == "code":
            self.code = max(0, self.code - 1)
        elif tag == "span":
            kind = self.spans.pop() if self.spans else None
            self.bold = max(0, self.bold - (kind == "bold"))
            self.muted = max(0, self.muted - (kind == "muted"))
        elif tag == "pre":
            self.ensure_nl()
            self.pre = max(0, self.pre - 1)
        elif tag == "a":
            self.link = None
        elif tag in ("ul", "ol"):
            self.ensure_nl()
            if self.lists:
                self.lists.pop()
        elif tag == "li":
            self.ensure_nl()
        elif tag == "blockquote":
            self.ensure_nl()
            self.quote = max(0, self.quote - 1)

    def handle_data(self, data):
        if self.table is not None:
            if self.table["cell"] is not None:
                self.table["cell"].append(data)
            return
        if self.pre:
            self.write(data)
            return
        cjk = "　-鿿＀-￯"
        data = re.sub("(?<=[%s])\n(?=[%s])" % (cjk, cjk), "", data)
        data = re.sub(r"[ \t\r\n]+", " ", data)
        if not self.tail or self.tail.endswith(("\n", " ")):
            data = data.lstrip(" ")
        self.write(data)

    # --- 表 -------------------------------------------------------
    def draw_table(self, rows):
        """文字数ではなくピクセル幅で列を揃える（日本語でもずれない）。"""
        if not rows:
            return
        cols = max(len(r) for r in rows)
        rows = [r + [("", "left")] * (cols - len(r)) for r in rows]
        app = self.app
        reg = app.fonts[app.font_tag(False, 0, False, False)]
        bold = app.fonts[app.font_tag(False, 0, True, False)]
        gap = 28
        text_w = [max((bold if n == 0 else reg).measure(r[c][0])
                      for n, r in enumerate(rows)) for c in range(cols)]
        stops, x = [], 6
        for c in range(cols):
            align = rows[0][c][1]
            if align == "right":
                stops += [x + text_w[c], "right"]
            elif align == "center":
                stops += [x + text_w[c] // 2, "center"]
            else:
                stops += [x, "left"]
            x += text_w[c] + gap
        tag = app.table_tag(stops)
        for n, r in enumerate(rows):
            if n == 0:
                self.bold += 1
            self.write("".join("\t" + r[c][0] for c in range(cols)) + "\n",
                       (tag,))
            if n == 0:
                self.bold -= 1
                k = max(1, (x - gap) // max(1, reg.measure("─")))
                self.write("─" * k + "\n", ("hr",))


class App:
    def __init__(self, root, path=None, state_path=None):
        self.root = root
        self.state_path = Path(state_path) if state_path else \
            default_state_path()
        # 旧名（MD Editor）の保存先。新しい保存先がまだ無いときだけ、読み込みに使う
        self.legacy_state_path = None if state_path else legacy_state_path()
        self.mod = "Command" if sys.platform == "darwin" else "Control"
        self.mod_label = "⌘" if sys.platform == "darwin" else "Ctrl+"
        self.path = None
        self.name = "無題.md"
        self.dirty = False
        self.newline = "\n"
        self.bom = False
        self.loading = False
        self.render_job = self.save_job = None
        self.stale = False  # プレビューが非表示の間に、描き直しが必要になったか
        self.last_render_ms = 0.0
        self.fonts = {}
        self.made_tags = set()
        self.link_tags = []
        self.links = {}
        self.link_n = 0

        state = self.read_state()
        self.theme = state.get("theme", "light")
        if self.theme not in THEMES:
            self.theme = "light"
        self.size = int(state.get("size", 12)) if str(
            state.get("size", 12)).isdigit() else 12
        self.mode_var = tk.StringVar(
            value=state.get("mode") if state.get("mode") in
            ("split", "editor", "preview") else "split")
        self.theme_var = tk.StringVar(value=self.theme)
        # プレビューの本文のフォント。空なら標準。この PC に無いフォントは使わない
        self.pv_family = str(state.get("preview_font") or "")
        if self.pv_family not in ("", *self.font_families()):
            self.pv_family = ""
        self.font_dialog = None

        self.build_ui()
        self.apply_theme()
        self.set_mode()

        draft = state.get("draft")
        if path:
            self.open_path(path)
        elif isinstance(draft, dict) and isinstance(draft.get("text"), str):
            self.set_text(draft["text"])
            self.name = draft.get("name") or self.name
            p = draft.get("path")
            self.path = Path(p) if p else None
            self.dirty = bool(draft.get("dirty"))
            self.refresh_title()
        else:
            self.set_text(SAMPLE)
        self.render()
        root.protocol("WM_DELETE_WINDOW", self.quit)

    # --- 状態の保存 -----------------------------------------------
    def read_state(self):
        path = self.state_path
        if not path.exists() and self.legacy_state_path:
            path = self.legacy_state_path  # 書くのは常に新しい保存先
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def write_state(self):
        self.cancel_job(self.save_job)  # 直接呼ばれても、予約済みの保存を残さない
        self.save_job = None
        state = dict(theme=self.theme, size=self.size,
                     mode=self.mode_var.get(),
                     preview_font=self.pv_family)
        if self.dirty or self.path is None:
            state["draft"] = dict(text=self.ed.get("1.0", "end-1c"),
                                  name=self.name,
                                  path=str(self.path) if self.path else None,
                                  dirty=self.dirty)
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(state, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # 保存できなくても編集は止めない

    def schedule_save(self):
        self.cancel_job(self.save_job)
        self.save_job = self.root.after(800, self.write_state)

    # --- UI -------------------------------------------------------
    def build_ui(self):
        r = self.root
        r.geometry("1100x700")
        self.paned = ttk.PanedWindow(r, orient="horizontal")
        self.status = ttk.Label(r, anchor="w", padding=(8, 2))
        self.status.pack(side="bottom", fill="x")
        self.paned.pack(side="top", fill="both", expand=True)

        self.left = ttk.Frame(self.paned)
        self.right = ttk.Frame(self.paned)
        self.ed = tk.Text(self.left, undo=True, wrap="word", padx=10, pady=8,
                          borderwidth=0, highlightthickness=0,
                          insertwidth=2)
        self.pv = tk.Text(self.right, wrap="word", padx=14, pady=10,
                          borderwidth=0, highlightthickness=0,
                          cursor="arrow", state="disabled")
        for frame, text in ((self.left, self.ed), (self.right, self.pv)):
            sb = ttk.Scrollbar(frame, command=text.yview)
            text.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            text.pack(side="left", fill="both", expand=True)

        self.edfont = tkfont.nametofont("TkFixedFont").copy()
        self.ed.configure(font=self.edfont)
        self.ed.bind("<<Modified>>", self.on_modified)
        self.pv_width = 0
        self.pv.bind("<Configure>", self.on_resize)

        self.build_menu()
        m = self.mod
        binds = {
            "n": self.new, "o": self.open_dialog, "s": self.save,
            "S": self.save_as, "e": self.export,
            "equal": lambda: self.zoom(1), "plus": lambda: self.zoom(1),
            "minus": lambda: self.zoom(-1),
        }
        for w in (self.ed, self.pv):
            for key, fn in binds.items():
                w.bind("<%s-%s>" % (m, key), lambda e, f=fn: (f(), "break")[1])
            # Tk 既定の Ctrl+O（行を開く）などより先に処理する
            w.bind("<%s-Shift-s>" % m, lambda e: (self.save_as(), "break")[1])

    def build_menu(self):
        mod = self.mod_label
        bar = tk.Menu(self.root)
        f = tk.Menu(bar, tearoff=False)
        f.add_command(label="新規", accelerator=mod + "N", command=self.new)
        f.add_command(label="開く…", accelerator=mod + "O",
                      command=self.open_dialog)
        f.add_command(label="保存", accelerator=mod + "S", command=self.save)
        f.add_command(label="名前を付けて保存…", accelerator=mod + "Shift+S",
                      command=self.save_as)
        f.add_separator()
        f.add_command(label="HTML として書き出し…", accelerator=mod + "E",
                      command=self.export)
        self.file_menu, self.export_index = f, f.index("end")
        f.add_separator()
        f.add_command(label="終了", command=self.quit)
        bar.add_cascade(label="ファイル", menu=f)

        v = tk.Menu(bar, tearoff=False)
        for label, val in (("分割", "split"), ("エディタのみ", "editor"),
                           ("プレビューのみ", "preview")):
            v.add_radiobutton(label=label, value=val,
                              variable=self.mode_var, command=self.set_mode)
        v.add_separator()
        for label, val in (("ライト", "light"), ("ダーク", "dark")):
            v.add_radiobutton(label=label + "テーマ", value=val,
                              variable=self.theme_var, command=self.set_theme)
        v.add_separator()
        v.add_command(label="文字を大きく", accelerator=mod + "+",
                      command=lambda: self.zoom(1))
        v.add_command(label="文字を小さく", accelerator=mod + "-",
                      command=lambda: self.zoom(-1))
        v.add_command(label="プレビューのフォント…",
                      command=self.open_font_dialog)
        bar.add_cascade(label="表示", menu=v)
        self.root.config(menu=bar)

    def set_mode(self):
        for p in self.paned.panes():
            self.paned.forget(p)
        mode = self.mode_var.get()
        if mode in ("split", "editor"):
            self.paned.add(self.left, weight=1)
        if mode in ("split", "preview"):
            self.paned.add(self.right, weight=1)
        if self.stale and self.preview_visible():
            self.render()
        self.schedule_save()

    def set_theme(self):
        self.theme = self.theme_var.get()
        self.apply_theme()
        self.render()
        self.schedule_save()

    def zoom(self, d):
        self.size = max(8, min(36, self.size + d))
        self.edfont.configure(size=self.size)
        self.fonts.clear()
        self.made_tags.clear()
        self.render()
        self.schedule_save()

    def apply_theme(self):
        t = THEMES[self.theme]
        self.edfont.configure(size=self.size)
        self.ed.configure(bg=t["bg"], fg=t["fg"], insertbackground=t["fg"],
                          selectbackground=t["sel"], selectforeground=t["fg"])
        self.pv.configure(bg=t["bg"], fg=t["fg"], selectbackground=t["sel"],
                          selectforeground=t["fg"])
        self.status.configure(background=t["panel"], foreground=t["muted"])
        pv = self.pv
        pv.tag_configure("strike", overstrike=True)
        pv.tag_configure("code", background=t["code"])
        pv.tag_configure("pre", background=t["pre"])
        pv.tag_configure("quote", foreground=t["muted"])
        pv.tag_configure("hr", foreground=t["rule"])
        self.made_tags.clear()
        self.fonts.clear()

    # --- プレビューのフォント -------------------------------------
    def font_families(self):
        """この PC で使える本文向けのフォント名（縦書き用の '@' 付きは除く）。"""
        return sorted({f for f in tkfont.families(self.root)
                       if not f.startswith("@")}, key=str.casefold)

    def set_preview_font(self, family):
        """family が空なら標準に戻す。使えないフォント名は受け付けない。"""
        if family and family not in self.font_families():
            return False
        self.pv_family = family
        self.fonts.clear()
        self.made_tags.clear()
        self.render()
        self.schedule_save()
        return True

    def open_font_dialog(self):
        """フォントを選ぶ小さなウィンドウ。選んだ時点でプレビューに反映する。"""
        if self.font_dialog and self.font_dialog.winfo_exists():
            self.font_dialog.lift()
            return self.font_dialog
        win = tk.Toplevel(self.root)
        win.title("プレビューのフォント")
        win.transient(self.root)
        win.geometry("340x420")
        self.font_dialog = win
        families = self.font_families()
        query = tk.StringVar()
        ttk.Label(win, text="フォント名で絞り込み", padding=(10, 8, 10, 2)
                  ).pack(anchor="w")
        entry = ttk.Entry(win, textvariable=query)
        entry.pack(fill="x", padx=10)
        box = ttk.Frame(win)
        box.pack(fill="both", expand=True, padx=10, pady=8)
        sb = ttk.Scrollbar(box)
        lb = tk.Listbox(box, exportselection=False, activestyle="none",
                        yscrollcommand=sb.set)
        sb.configure(command=lb.yview)
        sb.pack(side="right", fill="y")
        lb.pack(side="left", fill="both", expand=True)
        win.listbox = lb  # テストから触れるようにする

        def fill(*_):
            q = query.get().strip().casefold()
            lb.delete(0, "end")
            shown = [f for f in families if q in f.casefold()]
            for f in shown:
                lb.insert("end", f)
            if self.pv_family in shown:
                i = shown.index(self.pv_family)
                lb.selection_set(i)
                lb.see(i)

        def choose(_event=None):
            sel = lb.curselection()
            if sel:
                self.set_preview_font(lb.get(sel[0]))

        def reset():
            self.set_preview_font("")
            lb.selection_clear(0, "end")

        query.trace_add("write", fill)
        lb.bind("<<ListboxSelect>>", choose)
        buttons = ttk.Frame(win)
        buttons.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(buttons, text="標準に戻す", command=reset).pack(side="left")
        ttk.Button(buttons, text="閉じる", command=win.destroy
                   ).pack(side="right")
        fill()
        entry.focus_set()
        return win

    # --- プレビュー用タグ -----------------------------------------
    def font_tag(self, fixed, heading, bold, italic):
        name = "f%d%d%d%d" % (fixed, heading, bold, italic)
        if name not in self.made_tags:
            base = tkfont.nametofont("TkFixedFont" if fixed
                                     else "TkDefaultFont")
            # 選んだフォントは本文用。コードは常に等幅フォントのまま
            family = (self.pv_family if self.pv_family and not fixed
                      else base.actual("family"))
            size = max(8, round(self.size * HEADING_SCALE.get(heading, 1.0)))
            f = tkfont.Font(family=family, size=size,
                            weight="bold" if bold else "normal",
                            slant="italic" if italic else "roman")
            self.fonts[name] = f
            self.pv.tag_configure(name, font=f)
            self.made_tags.add(name)
        return name

    def margin_tag(self, quote, depth):
        name = "m%d_%d" % (quote, depth)
        if name not in self.made_tags:
            base = 18 * quote
            if depth:
                l1, l2 = base + 20 * (depth - 1) + 4, base + 20 * depth + 4
            else:
                l1, l2 = 0, base  # 1 行目に引用の目印を置き、折り返しは字下げ
            self.pv.tag_configure(name, lmargin1=l1, lmargin2=l2)
            self.made_tags.add(name)
        return name

    def table_tag(self, stops):
        self.table_n = getattr(self, "table_n", 0) + 1
        name = "tbl%d" % self.table_n
        self.pv.tag_configure(name, tabs=tuple(stops), spacing1=2, spacing3=2)
        self.link_tags.append(name)  # 描画のたびに link と一緒に削除する
        return name

    def link_tag(self, href):
        self.link_n += 1
        name = "link%d" % self.link_n
        t = THEMES[self.theme]
        pv = self.pv
        pv.tag_configure(name, foreground=t["link"], underline=True)
        pv.tag_bind(name, "<Button-1>", lambda e, h=href: self.open_link(h))
        pv.tag_bind(name, "<Enter>", lambda e: pv.configure(cursor="hand2"))
        pv.tag_bind(name, "<Leave>", lambda e: pv.configure(cursor="arrow"))
        self.link_tags.append(name)
        return name

    def open_link(self, href):
        # http / https / mailto / tel 以外（javascript: など）は開かない
        if re.match(r"(https?|mailto|tel):", href, re.I):
            webbrowser.open(href)

    # --- 描画 -----------------------------------------------------
    def on_modified(self, _event=None):
        if not self.ed.edit_modified():
            return
        self.ed.edit_modified(False)
        if self.loading:
            return
        self.dirty = True
        self.refresh_title()
        self.schedule_render(self.render_delay())
        self.schedule_save()

    def on_resize(self, event):
        # 水平線の長さが幅に依存するので、幅が変わったときだけ描き直す
        if event.width == self.pv_width:
            return
        self.pv_width = event.width
        self.schedule_render(150)

    def is_org(self):
        """ファイル名が .org なら Org として、それ以外は Markdown として解釈する。"""
        return self.name.lower().endswith(".org")

    def to_html(self, text):
        return (org_to_html if self.is_org() else md_to_html)(text)

    def preview_visible(self):
        return self.mode_var.get() in ("split", "preview")

    def render_delay(self):
        return int(min(RENDER_MAX_MS,
                       max(RENDER_MIN_MS, self.last_render_ms * 3)))

    def schedule_render(self, delay):
        self.cancel_job(self.render_job)
        self.render_job = self.root.after(delay, self.render)

    def update_status(self, text):
        body = re.sub(r"\s", "", text)
        self.status.configure(
            text="%d 行 / %d 文字（空白除く）" % (
                text.count("\n") + 1 if text else 0, len(body)))

    def render(self):
        # 直接呼ばれたときに、予約済みの描き直しが残って二重に描かないようにする
        self.cancel_job(self.render_job)
        self.render_job = None
        text = self.ed.get("1.0", "end-1c")
        self.update_status(text)
        if not self.preview_visible():
            self.stale = True  # 表示に切り替えたときに描く
            return
        self.stale = False
        start = time.perf_counter()
        html, notice = "", None
        try:
            html = self.to_html(text)
        except RecursionError:
            notice = "入れ子が深すぎて、プレビューを描画できません。"
        except Exception as e:  # 解析の失敗でエディタを止めない
            notice = "プレビューを作れませんでした（%s）。" % type(e).__name__
        pv = self.pv
        top = pv.yview()[0]
        pv.configure(state="normal")
        try:
            pv.delete("1.0", "end")
            for name in self.link_tags:
                pv.tag_delete(name)
            self.link_tags.clear()
            if not notice:
                try:
                    r = Renderer(self)
                    r.feed(html)
                    r.close()
                except Exception as e:  # 描画の失敗でも状態は必ず戻す
                    pv.delete("1.0", "end")
                    notice = "プレビューの描画に失敗しました（%s）。" % \
                        type(e).__name__
            if notice:
                pv.insert("end", notice, ("quote",))
        finally:
            pv.configure(state="disabled")
        pv.yview_moveto(top)
        self.last_render_ms = (time.perf_counter() - start) * 1000

    def refresh_title(self):
        self.root.title("%s%s — %s" % ("● " if self.dirty else "",
                                       self.name, APP))
        # Org は編集だけ。HTML への書き出しは選べなくする
        self.file_menu.entryconfigure(
            self.export_index, state="disabled" if self.is_org() else "normal")

    # --- ファイル操作 ---------------------------------------------
    def set_text(self, text):
        self.loading = True
        self.ed.delete("1.0", "end")
        self.ed.insert("1.0", text)
        self.ed.edit_reset()
        self.ed.edit_modified(False)
        self.loading = False
        self.ed.mark_set("insert", "1.0")
        self.ed.see("1.0")
        self.dirty = False
        self.refresh_title()

    def ok_discard(self):
        if not self.dirty:
            return True
        ans = messagebox.askyesnocancel(
            APP, "未保存の変更があります。保存しますか？")
        if ans is None:
            return False
        return self.save() if ans else True

    def new(self):
        if not self.ok_discard():
            return
        self.path, self.name = None, "無題.md"
        self.newline, self.bom = "\n", False
        self.set_text("")
        self.render()
        self.schedule_save()

    def open_dialog(self):
        if not self.ok_discard():
            return
        p = filedialog.askopenfilename(
            filetypes=[("Markdown / Org", "*.md *.markdown *.org *.txt"),
                       ("すべてのファイル", "*")])
        if p:
            self.open_path(p)

    def open_path(self, p):
        p = Path(p)
        try:
            raw = p.read_bytes()
            text = raw.decode("utf-8-sig")
        except OSError as e:
            messagebox.showerror(APP, "開けませんでした:\n%s" % e)
            return
        except UnicodeDecodeError:
            messagebox.showerror(
                APP, "UTF-8 として読み込めませんでした。\n"
                     "このエディタは UTF-8 のファイルだけを扱います。")
            return
        self.bom = raw.startswith(b"\xef\xbb\xbf")
        self.newline = "\r\n" if b"\r\n" in raw else "\n"
        self.path, self.name = p, p.name
        self.set_text(text.replace("\r\n", "\n").replace("\r", "\n"))
        self.render()
        self.schedule_save()

    def write_file(self, p, text, encoding, newline):
        with open(p, "w", encoding=encoding, newline=newline) as f:
            f.write(text)

    def save(self):
        if self.path is None:
            return self.save_as()
        try:
            self.write_file(self.path, self.ed.get("1.0", "end-1c"),
                            "utf-8-sig" if self.bom else "utf-8",
                            self.newline)
        except OSError as e:
            messagebox.showerror(APP, "保存できませんでした:\n%s" % e)
            return False
        self.dirty = False
        self.refresh_title()
        self.schedule_save()
        return True

    def save_as(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".md", initialfile=self.name,
            filetypes=[("Markdown", "*.md"), ("Org", "*.org"),
                       ("すべてのファイル", "*")])
        if not p:
            return False
        self.path, self.name = Path(p), Path(p).name
        self.render()  # 拡張子で、Markdown と Org の解釈が変わる
        return self.save()

    def export(self):
        if self.is_org():  # Org は編集だけ。HTML への書き出しは Markdown のみ
            messagebox.showinfo(APP, "Org ファイルは HTML に書き出せません。")
            return
        stem = Path(self.name).stem
        p = filedialog.asksaveasfilename(
            defaultextension=".html", initialfile=stem + ".html",
            filetypes=[("HTML", "*.html")])
        if not p:
            return
        try:
            self.write_file(p, export_html(stem, self.ed.get("1.0", "end-1c")),
                            "utf-8", "\n")
        except OSError as e:
            messagebox.showerror(APP, "書き出せませんでした:\n%s" % e)

    def cancel_job(self, job):
        if job:
            try:
                self.root.after_cancel(job)
            except tk.TclError:  # 破棄済みのウィンドウでも止められるように
                pass

    def cancel_jobs(self):
        self.cancel_job(self.render_job)
        self.cancel_job(self.save_job)
        self.render_job = self.save_job = None

    def quit(self):
        if not self.ok_discard():
            return
        self.cancel_jobs()
        self.write_state()
        self.root.destroy()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = tk.Tk()
    App(root, argv[0] if argv else None)
    root.mainloop()


if __name__ == "__main__":
    main()
