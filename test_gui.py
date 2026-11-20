"""md_editor.py の GUI テスト。実際に tkinter のウィンドウを開いて確認する。

画面を開けない環境（DISPLAY のない Linux など）では、全体をスキップする。
ダイアログは差し替えるので、人の操作は要らない。
"""
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import md_editor as m


def _has_display():
    try:
        r = tk.Tk()
    except tk.TclError:
        return False
    r.destroy()
    return True


HAVE_DISPLAY = _has_display()
KEYSYMS = {"\n": "Return", " ": "space", "#": "numbersign", "*": "asterisk"}


def pump(root, ms=500):
    """イベントループを ms ミリ秒まわす（間引き描画を待つ）。"""
    end = time.time() + ms / 1000
    while time.time() < end:
        root.update()
        time.sleep(0.01)


@unittest.skipUnless(HAVE_DISPLAY, "画面を開けない環境")
class GuiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.state = self.dir / "state.json"
        self.asked = []
        patches = [
            mock.patch.object(m.messagebox, "askyesnocancel",
                              side_effect=lambda *a, **k: (
                                  self.asked.append("askyesnocancel"), False
                              )[1]),
            mock.patch.object(m.messagebox, "showerror",
                              side_effect=lambda *a, **k: self.asked.append(
                                  "showerror")),
            mock.patch.object(m.filedialog, "askopenfilename",
                              side_effect=lambda *a, **k: (
                                  self.asked.append("askopen"), "")[1]),
            mock.patch.object(m.filedialog, "asksaveasfilename",
                              side_effect=lambda *a, **k: (
                                  self.asked.append("asksave"), "")[1]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.root = tk.Tk()
        self.root.geometry("900x600")
        self.apps = []
        self.addCleanup(self.shutdown)
        self.app = self.new_app()

    def shutdown(self):
        self.root.destroy()
        # 破棄の最中に予約されたタイマーが、次のテストで動かないように止める
        for app in self.apps:
            app.cancel_jobs()
        self.tmp.cleanup()

    def new_app(self, path=None):
        app = m.App(self.root, path, state_path=self.state)
        self.apps.append(app)
        self.root.update()
        app.ed.focus_force()
        self.root.update()
        return app

    def preview(self):
        return self.app.pv.get("1.0", "end-1c")

    def type_text(self, text):
        self.app.ed.mark_set("insert", "end-1c")  # 末尾に入力する
        for ch in text:
            self.app.ed.event_generate("<Key>", keysym=KEYSYMS.get(ch, ch))

    # --- 編集とプレビュー -----------------------------------------
    def test_typing_updates_preview_and_marks_dirty(self):
        app = self.app
        app.set_text("")
        self.type_text("# Hi\n\n**b** x")
        pump(self.root)
        self.assertEqual(app.ed.get("1.0", "end-1c"), "# Hi\n\n**b** x")
        self.assertEqual(self.preview(), "Hi\n\nb x\n")
        self.assertTrue(app.dirty)
        self.assertTrue(self.root.title().startswith("●"))

    def test_preview_is_read_only_state(self):
        self.app.render()
        self.assertEqual(str(self.app.pv.cget("state")), "disabled")

    # --- ショートカット -------------------------------------------
    def test_ctrl_o_opens_dialog_without_editing_text(self):
        app = self.app
        app.set_text("keep")
        before = app.ed.get("1.0", "end-1c")
        app.ed.event_generate("<Control-o>")
        self.root.update()
        self.assertIn("askopen", self.asked)
        # Tk 既定の Ctrl+O（行を開く）が効いていないこと
        self.assertEqual(app.ed.get("1.0", "end-1c"), before)

    def test_ctrl_s_saves_to_path(self):
        app = self.app
        app.path = self.dir / "a.md"
        app.name = "a.md"
        app.set_text("x")
        self.type_text("y")
        pump(self.root, 200)
        self.assertTrue(app.dirty)
        app.ed.event_generate("<Control-s>")
        self.root.update()
        self.assertEqual(app.path.read_text(encoding="utf-8"), "xy")
        self.assertFalse(app.dirty)

    def test_ctrl_plus_minus_changes_font_size(self):
        app = self.app
        s0 = app.size
        app.ed.event_generate("<Control-equal>")
        self.root.update()
        self.assertEqual(app.size, s0 + 1)
        app.ed.event_generate("<Control-minus>")
        app.ed.event_generate("<Control-minus>")
        self.root.update()
        self.assertEqual(app.size, s0 - 1)

    # --- ファイル -------------------------------------------------
    def test_bom_and_crlf_are_preserved_on_save(self):
        p = self.dir / "w.md"
        p.write_bytes("﻿# T\r\n\r\n本文\r\n".encode("utf-8"))
        app = self.app
        app.open_path(p)
        self.assertEqual(app.ed.get("1.0", "end-1c"), "# T\n\n本文\n")
        app.ed.insert("end", "追記")
        app.save()
        self.assertEqual(
            p.read_bytes(),
            "﻿# T\r\n\r\n本文\r\n追記".encode("utf-8"))

    def test_non_utf8_file_is_rejected_without_touching_editor(self):
        p = self.dir / "sjis.md"
        p.write_bytes("日本語".encode("cp932"))
        app = self.app
        app.set_text("original")
        app.open_path(p)
        self.assertIn("showerror", self.asked)
        self.assertEqual(app.ed.get("1.0", "end-1c"), "original")

    def test_new_asks_before_discarding_changes(self):
        app = self.app
        app.set_text("a")
        self.type_text("b")
        pump(self.root, 200)
        app.new()  # ダイアログは「保存しない」を返す
        self.assertIn("askyesnocancel", self.asked)
        self.assertEqual(app.ed.get("1.0", "end-1c"), "")
        self.assertEqual(app.name, "無題.md")

    def test_export_html_is_self_contained(self):
        out = self.dir / "o.html"
        with mock.patch.object(m.filedialog, "asksaveasfilename",
                               return_value=str(out)):
            self.app.set_text("# Title")
            self.app.export()
        html = out.read_text(encoding="utf-8")
        self.assertIn("<h1>Title</h1>", html)
        self.assertNotIn("https://", html)

    # --- 描画の堅牢性と効率 ---------------------------------------
    def test_render_failure_restores_state_and_shows_notice(self):
        app = self.app
        app.set_text("".join("  " * i + "- x\n" for i in range(3000)))
        app.render()  # RecursionError でも例外を外に出さない
        self.assertEqual(str(app.pv.cget("state")), "disabled")
        self.assertIn("入れ子が深すぎて", self.preview())
        app.set_text("# ok")
        app.render()
        self.assertEqual(self.preview(), "ok\n")

    def test_renderer_exception_restores_state(self):
        app = self.app
        app.set_text("text")
        with mock.patch.object(m.Renderer, "feed",
                               side_effect=ValueError("boom")):
            app.render()
        self.assertEqual(str(app.pv.cget("state")), "disabled")
        self.assertIn("描画に失敗", self.preview())

    def test_hidden_preview_is_not_rendered_until_shown(self):
        app = self.app
        app.set_text("# A")
        app.render()
        self.assertEqual(self.preview(), "A\n")
        app.mode_var.set("editor")
        app.set_mode()
        app.set_text("# B")
        app.render()
        self.assertTrue(app.stale)
        self.assertEqual(self.preview(), "A\n")  # 描いていない
        self.assertIn("1 行", app.status.cget("text"))  # 状態表示は更新する
        app.mode_var.set("split")
        app.set_mode()
        self.assertFalse(app.stale)
        self.assertEqual(self.preview(), "B\n")

    def test_render_delay_grows_with_render_cost(self):
        app = self.app
        app.last_render_ms = 0
        self.assertEqual(app.render_delay(), m.RENDER_MIN_MS)
        app.last_render_ms = 200
        self.assertEqual(app.render_delay(), 600)
        app.last_render_ms = 10_000
        self.assertEqual(app.render_delay(), m.RENDER_MAX_MS)

    def test_render_does_not_leak_tags(self):
        app = self.app
        app.set_text("[a](https://e.com)\n\n| a |\n|---|\n| 1 |\n")
        app.render()
        n = len(app.pv.tag_names())
        for _ in range(20):
            app.render()
        self.assertEqual(len(app.pv.tag_names()), n)

    # --- 表示 -----------------------------------------------------
    def test_table_columns_use_tab_stops(self):
        app = self.app
        app.set_text("| 左 | 右 |\n|:--|--:|\n| あ | 12345 |\n")
        app.render()
        lines = self.preview().split("\n")
        self.assertEqual(lines[0], "\t左\t右")
        self.assertEqual(lines[2], "\tあ\t12345")

    def test_links_open_only_safe_schemes(self):
        with mock.patch.object(m.webbrowser, "open") as opened:
            for url in ("#", "javascript:alert(1)", "file:///etc/passwd",
                        "https://e.com", "mailto:a@b.co"):
                self.app.open_link(url)
        self.assertEqual([c.args[0] for c in opened.call_args_list],
                         ["https://e.com", "mailto:a@b.co"])

    # --- プレビューのフォント -------------------------------------
    def font_family_at(self, word):
        pv = self.app.pv
        index = pv.search(word, "1.0")
        for tag in pv.tag_names(index):
            if tag in self.app.fonts:
                return self.app.fonts[tag].cget("family")
        self.fail("%r にフォントのタグが無い" % word)

    def other_family(self):
        default = m.tkfont.nametofont("TkDefaultFont").actual("family")
        return next(f for f in self.app.font_families() if f != default)

    def test_preview_font_applies_to_body_but_not_code(self):
        app = self.app
        fam = self.other_family()
        app.set_text("# Head\n\nbody `code`\n")
        self.assertTrue(app.set_preview_font(fam))
        self.assertEqual(self.font_family_at("body"), fam)
        self.assertEqual(self.font_family_at("Head"), fam)
        self.assertNotEqual(self.font_family_at("code"), fam)  # 等幅のまま

    def test_preview_font_reset_and_invalid(self):
        app = self.app
        fam = self.other_family()
        app.set_text("body")
        app.set_preview_font(fam)
        self.assertFalse(app.set_preview_font("No Such Font 12345"))
        self.assertEqual(app.pv_family, fam)  # 変わらない
        self.assertTrue(app.set_preview_font(""))
        default = m.tkfont.nametofont("TkDefaultFont").actual("family")
        self.assertEqual(self.font_family_at("body"), default)

    def test_preview_font_is_saved_and_unknown_font_is_ignored(self):
        app = self.app
        fam = self.other_family()
        app.set_preview_font(fam)
        app.write_state()
        for w in self.root.winfo_children():
            w.destroy()
        self.assertEqual(self.new_app().pv_family, fam)
        self.state.write_text('{"preview_font": "No Such Font 12345"}',
                              encoding="utf-8")
        for w in self.root.winfo_children():
            w.destroy()
        self.assertEqual(self.new_app().pv_family, "")

    def test_font_dialog_selects_and_resets(self):
        app = self.app
        win = app.open_font_dialog()
        self.root.update()
        self.assertIs(app.open_font_dialog(), win)  # 二重に開かない
        lb = win.listbox
        self.assertGreater(lb.size(), 0)
        lb.selection_clear(0, "end")
        lb.selection_set(0)
        lb.event_generate("<<ListboxSelect>>")
        self.root.update()
        self.assertEqual(app.pv_family, lb.get(0))
        app.set_preview_font("")
        self.assertEqual(app.pv_family, "")
        win.destroy()

    # --- 設定の保存 -----------------------------------------------
    def test_state_roundtrip_restores_draft_and_theme(self):
        app = self.app
        app.set_text("draft")
        self.type_text("!")
        pump(self.root, 200)
        app.theme_var.set("dark")
        app.set_theme()
        app.write_state()
        for w in self.root.winfo_children():
            w.destroy()
        app2 = self.new_app()
        self.assertEqual(app2.theme, "dark")
        self.assertEqual(app2.ed.get("1.0", "end-1c"), "draft!")
        self.assertTrue(app2.dirty)

    def test_state_write_failure_is_ignored(self):
        self.app.state_path = self.dir  # ディレクトリには書けない
        self.app.write_state()  # 例外にならないこと


if __name__ == "__main__":
    unittest.main()
