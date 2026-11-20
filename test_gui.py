"""markup_editor.py の GUI テスト。実際に tkinter のウィンドウを開いて確認する。

画面を開けない環境（DISPLAY のない Linux など）では、全体をスキップする。
ダイアログは差し替えるので、人の操作は要らない。
"""
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

import markup_editor as m


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

    def reset_widgets(self):
        """アプリを作り直す前に、古いアプリのタイマーを止めて、画面部品を破棄する。"""
        for app in self.apps:
            app.cancel_jobs()
        for w in self.root.winfo_children():
            w.destroy()

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

    # --- Org ------------------------------------------------------
    ORG = "#+TITLE: メモ\n* TODO 買う :home:\n- [X] 卵\n本文の *太字* と /斜体/\n"

    def export_state(self):
        return str(self.app.file_menu.entrycget(self.app.export_index, "state"))

    def test_org_file_is_rendered_as_org_and_markdown_is_not(self):
        p = self.dir / "a.org"
        p.write_text(self.ORG, encoding="utf-8")
        app = self.app
        app.open_path(p)
        text = self.preview()
        self.assertIn("メモ", text)
        self.assertIn("TODO 買う", text)  # 見出しになり、* は表示されない
        self.assertNotIn("* TODO", text)
        self.assertIn("☑ 卵", text)
        self.assertNotIn("/斜体/", text)  # Org の斜体
        # 同じ文字でも、.md なら Markdown として解釈される
        app.name = "a.md"
        app.render()
        md = self.preview()
        self.assertIn("• TODO 買う", md)  # Markdown では箇条書き
        self.assertIn("/斜体/", md)  # Org の記号は、そのまま出る

    def test_extension_decides_the_format_case_insensitively(self):
        app = self.app
        for name, org in (("a.org", True), ("A.ORG", True), ("a.md", False),
                          ("a.org.md", False), ("org", False),
                          ("無題.md", False)):
            app.name = name
            self.assertEqual(app.is_org(), org, name)

    def test_todo_and_tag_are_styled_in_preview(self):
        app = self.app
        app.name = "a.org"
        app.set_text("* TODO 買う :home:\n")
        app.render()
        pv = app.pv
        todo = pv.search("TODO", "1.0")
        tag = pv.search(":home:", "1.0")
        self.assertEqual(
            app.fonts[next(t for t in pv.tag_names(todo)
                           if t in app.fonts)].cget("weight"), "bold")
        self.assertIn("quote", pv.tag_names(tag))  # 目立たない色
        self.assertNotIn("quote", pv.tag_names(pv.search("買う", "1.0")))

    def test_footnote_numbers_are_raised_and_planning_is_muted(self):
        app = self.app
        app.name = "a.org"
        app.set_text("* TODO 提出\nDEADLINE: <2024-05-10 Fri>\n"
                     "本文[fn:1]です。\n\n[fn:1] 補足\n")
        app.render()
        pv = app.pv
        text = self.preview()
        self.assertIn("本文1です。", text)  # 参照は番号に置き換わる
        self.assertNotIn("[fn:1]", text)
        self.assertIn("1 補足", text)
        # 番号は上付き（offset）で、目立たない色
        sup = pv.tag_names(pv.search("1", pv.search("本文", "1.0")))
        self.assertIn("sup", sup)
        self.assertGreater(int(float(pv.tag_cget("sup", "offset"))), 0)
        self.assertIn("quote", sup)
        # 予定の行は目立たない色。本文は通常の色
        plan = pv.search("DEADLINE", "1.0")
        self.assertIn("quote", pv.tag_names(plan))
        self.assertNotIn("quote", pv.tag_names(pv.search("です", "1.0")))

    def test_properties_drawer_is_not_shown_in_preview(self):
        app = self.app
        app.name = "a.org"
        app.set_text("* 見出し\n:PROPERTIES:\n:ID: abc123\n:END:\n本文\n")
        app.render()
        self.assertEqual(self.preview(), "見出し\n\n本文\n")

    def test_export_is_disabled_for_org_and_blocked_by_shortcut(self):
        app = self.app
        with mock.patch.object(m.messagebox, "showinfo") as info:
            self.assertEqual(self.export_state(), "normal")
            app.name = "a.org"
            app.refresh_title()
            self.assertEqual(self.export_state(), "disabled")
            app.export()  # Ctrl+E でも書き出さない
            self.assertEqual(info.call_count, 1)
            self.assertFalse(self.asked.count("asksave"))
        app.name = "a.md"
        app.refresh_title()
        self.assertEqual(self.export_state(), "normal")

    def test_save_as_org_switches_the_preview_format(self):
        app = self.app
        app.set_text("* 見出し\n")
        app.render()
        self.assertIn("• 見出し", self.preview())  # Markdown では箇条書き
        out = self.dir / "b.org"
        with mock.patch.object(m.filedialog, "asksaveasfilename",
                               return_value=str(out)):
            app.save_as()
        self.assertEqual(out.read_text(encoding="utf-8"), "* 見出し\n")
        self.assertNotIn("•", self.preview())  # Org の見出しになる
        self.assertEqual(self.export_state(), "disabled")

    def test_org_file_roundtrip_keeps_bytes(self):
        p = self.dir / "r.org"
        raw = "﻿* 見出し\r\n本文\r\n".encode("utf-8")
        p.write_bytes(raw)
        app = self.app
        app.open_path(p)
        app.save()
        self.assertEqual(p.read_bytes(), raw)

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
        self.reset_widgets()
        self.assertEqual(self.new_app().pv_family, fam)
        self.state.write_text('{"preview_font": "No Such Font 12345"}',
                              encoding="utf-8")
        self.reset_widgets()
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
        self.reset_widgets()
        app2 = self.new_app()
        self.assertEqual(app2.theme, "dark")
        self.assertEqual(app2.ed.get("1.0", "end-1c"), "draft!")
        self.assertTrue(app2.dirty)

    def test_state_write_failure_is_ignored(self):
        self.app.state_path = self.dir  # ディレクトリには書けない
        self.app.write_state()  # 例外にならないこと

    def test_state_location_and_legacy_migration(self):
        home = self.dir / "home"
        old = home / ".md-editor" / "state.json"
        new = home / ".markup-editor" / "state.json"
        old.parent.mkdir(parents=True)
        old.write_text('{"theme": "dark", "size": 14}', encoding="utf-8")
        with mock.patch.object(m.Path, "home", return_value=home):
            self.assertEqual(m.default_state_path(), new)
            self.reset_widgets()
            app = m.App(self.root)  # state_path を渡さない = 実際の保存先
            self.apps.append(app)
            self.root.update()
            # 新しい保存先がまだ無いので、旧名の保存先から引き継ぐ
            self.assertEqual((app.theme, app.size), ("dark", 14))
            self.assertFalse(new.exists())
            app.write_state()
            # 書くのは新しい保存先だけ。旧名のファイルは触らない
            self.assertTrue(new.exists())
            self.assertIn('"dark"', old.read_text(encoding="utf-8"))
            # 新しい保存先ができたら、そちらを優先する
            new.write_text('{"theme": "light", "size": 10}', encoding="utf-8")
            self.reset_widgets()
            app2 = m.App(self.root)
            self.apps.append(app2)
            self.assertEqual((app2.theme, app2.size), ("light", 10))


if __name__ == "__main__":
    unittest.main()
