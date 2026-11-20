import time
import unittest

from mdparser import export_html, md_to_html


class Security(unittest.TestCase):
    def test_script_is_escaped(self):
        self.assertEqual(md_to_html("<script>alert(1)</script>"),
                         "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>")

    def test_javascript_link_and_image(self):
        self.assertIn('href="#"', md_to_html("[x](javascript:alert(1))"))
        self.assertIn('src="#"', md_to_html("![a](javascript:alert(1))"))
        self.assertNotIn("javascript", md_to_html("[x](JaVaScRiPt:alert(1))"))
        self.assertNotIn("data:", md_to_html("[x](data:text/html,<b>)"))

    def test_attribute_injection(self):
        h = md_to_html('https://e.com/"onmouseover="alert(1)')
        self.assertNotIn('"onmouseover', h)

    def test_nul_cannot_forge_placeholder(self):
        self.assertEqual(md_to_html("a\x00b \x000\x00 x"), "<p>ab 0 x</p>")


class Blocks(unittest.TestCase):
    def test_nested_and_task_lists(self):
        self.assertEqual(
            md_to_html("- a\n  - b\n- [x] c"),
            "<ul><li>a<ul><li>b</li></ul></li>"
            '<li><input type="checkbox" disabled checked> c</li></ul>')

    def test_ordered_start(self):
        self.assertEqual(md_to_html("3. a\n4. b"),
                         '<ol start="3"><li>a</li><li>b</li></ol>')

    def test_loose_list(self):
        self.assertEqual(md_to_html("- a\n\n- b"),
                         "<ul><li><p>a</p></li><li><p>b</p></li></ul>")

    def test_quote_and_fence_in_list(self):
        self.assertIn("<blockquote><p>q</p></blockquote>",
                      md_to_html("- a\n  > q"))
        self.assertIn("<pre><code>c</code></pre>",
                      md_to_html("- a\n\n  ```\n  c\n  ```"))

    def test_lazy_quote(self):
        self.assertEqual(md_to_html("> a\nlazy"),
                         "<blockquote><p>a\nlazy</p></blockquote>")

    def test_fence_lengths(self):
        self.assertEqual(md_to_html("````\n```\n````"),
                         "<pre><code>```</code></pre>")
        self.assertEqual(md_to_html("```\n<b>&\n```"),
                         "<pre><code>&lt;b&gt;&amp;</code></pre>")

    def test_table(self):
        h = md_to_html("| a | b | c |\n|:--|:-:|--:|\n| 1 | x\\|y | 3 |")
        self.assertIn('<th style="text-align:left">a</th>', h)
        self.assertIn('<td style="text-align:center">x|y</td>', h)
        self.assertIn('<td style="text-align:right">3</td>', h)

    def test_table_short_and_long_rows(self):
        self.assertIn("<td></td>", md_to_html("| a | b |\n|---|---|\n| 1 |"))
        self.assertNotIn(">3<",
                         md_to_html("| a |\n|---|\n| 1 | 2 | 3 |"))

    def test_headings(self):
        self.assertEqual(md_to_html("## h ##"), "<h2>h</h2>")
        self.assertEqual(md_to_html("#nospace"), "<p>#nospace</p>")


class Inline(unittest.TestCase):
    def test_escape(self):
        self.assertEqual(md_to_html(r"\*not em\*"), "<p>*not em*</p>")

    def test_triple_emphasis(self):
        self.assertEqual(md_to_html("***x***"),
                         "<p><strong><em>x</em></strong></p>")

    def test_strikethrough(self):
        self.assertEqual(md_to_html("~~a~~ ~b~"),
                         "<p><del>a</del> <del>b</del></p>")
        self.assertEqual(md_to_html("~5 and ~10"), "<p>~5 and ~10</p>")

    def test_link_with_parens(self):
        h = md_to_html("[w](https://e.com/A_(b)) 後")
        self.assertIn('href="https://e.com/A_(b)"', h)
        self.assertTrue(h.endswith("</a> 後</p>"))

    def test_autolinks(self):
        h = md_to_html("see https://e.com/a. and www.e.com, a@b.co")
        self.assertIn('href="https://e.com/a"', h)
        self.assertIn('href="http://www.e.com"', h)
        self.assertIn('href="mailto:a@b.co"', h)

    def test_japanese_url_boundary(self):
        h = md_to_html("https://e.com/a日本語")
        self.assertIn('href="https://e.com/a"', h)
        self.assertTrue(h.endswith(">https://e.com/a</a>日本語</p>"))

    def test_code_span_not_autolinked(self):
        self.assertEqual(md_to_html("`https://e.com`"),
                         "<p><code>https://e.com</code></p>")


class Limits(unittest.TestCase):
    def test_emphasis_length_limit(self):
        self.assertIn("<strong>", md_to_html("**" + "あ" * 500 + "**"))
        self.assertNotIn("<strong>", md_to_html("**" + "あ" * 510 + "**"))

    def test_unclosed_markers_stay_fast(self):
        # 閉じていない記号が大量にあっても、時間が二乗で増えない
        # （上限が無いと、この入力は数秒かかる）
        for src in ("**a " * 16000, "~a " * 16000):
            t0 = time.perf_counter()
            md_to_html(src)
            self.assertLess(time.perf_counter() - t0, 3.0)

    def test_unclosed_brackets_stay_fast(self):
        for src in ("[" * 20000, "![" * 20000, "[a" * 20000):
            t0 = time.perf_counter()
            md_to_html(src)
            self.assertLess(time.perf_counter() - t0, 3.0)

    def test_link_text_length_limit(self):
        # 上限を超えたら、[ がそのまま出る（URL は別に自動リンクされる）
        self.assertTrue(md_to_html("[" + "あ" * 500 + "](https://e.com)")
                        .startswith("<p><a "))
        self.assertTrue(md_to_html("[" + "あ" * 510 + "](https://e.com)")
                        .startswith("<p>["))

    def test_deep_nesting_raises_recursion_error_only(self):
        # 深すぎる入れ子は RecursionError になる。呼び出し側（GUI）が受け止める
        deep = "".join("  " * i + "- x\n" for i in range(3000))
        with self.assertRaises(RecursionError):
            md_to_html(deep)


class Export(unittest.TestCase):
    def test_export_is_self_contained(self):
        h = export_html("t<>", "# x")
        self.assertIn("<title>t&lt;&gt;</title>", h)
        self.assertIn("<h1>x</h1>", h)
        self.assertNotIn("http://", h)
        self.assertNotIn("https://", h)


if __name__ == "__main__":
    unittest.main()
