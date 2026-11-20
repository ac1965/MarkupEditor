import time
import unittest

from orgparser import org_to_html as o


class Headings(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(o("* A\n** B\n*** C"),
                         "<h1>A</h1>\n<h2>B</h2>\n<h3>C</h3>")

    def test_level_is_capped_at_6(self):
        self.assertTrue(o("******** deep").startswith("<h6>"))

    def test_todo_done_and_tags(self):
        self.assertEqual(
            o("* TODO 買う :home:work:"),
            '<h1><span class="todo">TODO</span> 買う '
            '<span class="tag">:home:work:</span></h1>')
        self.assertIn('<span class="todo done">DONE</span>', o("* DONE x"))

    def test_star_without_space_is_not_a_heading(self):
        self.assertEqual(o("*bold* text"), "<p><strong>bold</strong> text</p>")

    def test_title_keyword_only(self):
        self.assertEqual(o("#+TITLE: メモ\n#+AUTHOR: me\n#+OPTIONS: toc:nil"),
                         '<h1 class="title">メモ</h1>')

    def test_comments_are_hidden(self):
        self.assertEqual(o("# comment\n本文\n#\n"), "<p>本文</p>")


class Inline(unittest.TestCase):
    def test_markers(self):
        self.assertEqual(
            o("*b* /i/ _u_ +s+ =v= ~c~"),
            "<p><strong>b</strong> <em>i</em> <u>u</u> <del>s</del> "
            "<code>v</code> <code>c</code></p>")

    def test_marker_rules(self):
        # 直前が英数字だったり、直後が英数字だったりすると、記号は強調にならない
        for text in ("snake_case_name", "C++ and C++", "/usr/bin/x",
                     "2*3*4", "a=b=c", "x * y * z"):
            self.assertNotRegex(o(text), "<(strong|em|u|del|code)>", text)

    def test_markers_next_to_punctuation(self):
        self.assertEqual(o("(*b*), /i/."),
                         "<p>(<strong>b</strong>), <em>i</em>.</p>")

    def test_verbatim_has_no_markup_inside(self):
        self.assertEqual(o("=*a* <b>="), "<p><code>*a* &lt;b&gt;</code></p>")

    def test_nested_emphasis(self):
        self.assertEqual(o("*/x/*"), "<p><strong><em>x</em></strong></p>")

    def test_links(self):
        h = o("[[https://e.com][説明 *強調*]] と [[https://e.com/a]]")
        self.assertIn('<a href="https://e.com" target="_blank" '
                      'rel="noopener noreferrer">説明 <strong>強調</strong></a>',
                      h)
        self.assertIn('>https://e.com/a</a>', h)

    def test_image_link(self):
        self.assertIn('<img alt="" src="./a.png">', o("[[./a.png]]"))

    def test_bare_url_trims_punctuation(self):
        h = o("see https://e.com/a. next")
        self.assertIn('href="https://e.com/a"', h)

    def test_url_with_slashes_is_not_italic(self):
        self.assertNotIn("<em>", o("https://e.com/a/b/c/d"))

    def test_code_marker_inside_url_query(self):
        self.assertNotIn("<code>", o("https://e.com/?a=1&b=2"))


class Security(unittest.TestCase):
    def test_script_is_escaped(self):
        self.assertEqual(o("<script>alert(1)</script>"),
                         "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>")

    def test_dangerous_urls(self):
        self.assertIn('href="#"', o("[[javascript:alert(1)][x]]"))
        self.assertIn('href="#"', o("[[javascript:alert(1)]]"))
        self.assertIn('src="#"', o("[[javascript:alert(1)//a.png]]"))
        self.assertIn('href="#"', o("[[file:/etc/passwd][x]]"))
        self.assertNotIn("javascript", o("[[JaVaScRiPt:alert(1)][x]]"))

    def test_src_block_is_escaped(self):
        self.assertIn("&lt;script&gt;",
                      o("#+BEGIN_SRC html\n<script>x</script>\n#+END_SRC"))

    def test_attribute_injection_in_language(self):
        h = o('#+BEGIN_SRC "onmouseover="alert(1)\nx\n#+END_SRC')
        self.assertNotIn('"onmouseover', h)

    def test_nul_cannot_forge_placeholder(self):
        self.assertEqual(o("a\x00b \x000\x00 x"), "<p>ab 0 x</p>")


class Blocks(unittest.TestCase):
    def test_paragraph_joins_lines(self):
        self.assertEqual(o("一行目\n二行目\n\n次の段落"),
                         "<p>一行目\n二行目</p>\n<p>次の段落</p>")

    def test_lists(self):
        self.assertEqual(
            o("- a\n  - b\n- c"),
            "<ul><li>a<ul><li>b</li></ul></li><li>c</li></ul>")
        self.assertEqual(o("+ a\n+ b"), "<ul><li>a</li><li>b</li></ul>")

    def test_ordered_list(self):
        self.assertEqual(o("1. a\n2) b"), "<ol><li>a</li><li>b</li></ol>")
        self.assertEqual(o("3. a\n4. b"),
                         '<ol start="3"><li>a</li><li>b</li></ol>')

    def test_star_bullet_must_be_indented(self):
        # 行頭の * は見出し。字下げした * は箇条書き
        self.assertEqual(o("- a\n* H"), "<ul><li>a</li></ul>\n<h1>H</h1>")
        self.assertEqual(o("  * a\n  * b"), "<ul><li>a</li><li>b</li></ul>")

    def test_checkbox(self):
        h = o("- [ ] a\n- [X] b\n- [x] c")
        self.assertEqual(h.count("checked"), 2)
        self.assertEqual(h.count('type="checkbox"'), 3)

    def test_partial_checkbox_is_unchecked(self):
        self.assertNotIn("checked", o("- [-] a"))

    def test_list_continuation_line(self):
        self.assertEqual(o("- a\n  続き\n- b"),
                         "<ul><li>a 続き</li><li>b</li></ul>")

    def test_list_continues_over_one_blank_line(self):
        self.assertEqual(o("- a\n\n- b"), "<ul><li>a</li><li>b</li></ul>")

    def test_src_block(self):
        self.assertEqual(
            o("#+BEGIN_SRC python\nprint(1)\n#+END_SRC"),
            '<pre><code class="lang-python">print(1)</code></pre>')
        self.assertEqual(o("#+begin_src\nx\n#+end_src"),
                         "<pre><code>x</code></pre>")

    def test_src_block_keeps_markup_and_unescapes_comma(self):
        h = o("#+BEGIN_SRC org\n,* not heading\n*bold*\n#+END_SRC")
        self.assertIn("* not heading\n*bold*", h)
        self.assertNotIn("<strong>", h)

    def test_unclosed_src_block_runs_to_end(self):
        self.assertEqual(o("#+BEGIN_SRC\nx\ny"), "<pre><code>x\ny</code></pre>")

    def test_quote_block(self):
        self.assertEqual(
            o("#+BEGIN_QUOTE\n引用 *強調*\n#+END_QUOTE"),
            "<blockquote><p>引用 <strong>強調</strong></p></blockquote>")

    def test_comment_block_is_hidden(self):
        self.assertEqual(o("#+BEGIN_COMMENT\n隠す\n#+END_COMMENT\n本文"),
                         "<p>本文</p>")

    def test_unknown_block_directives_are_dropped_but_body_is_kept(self):
        self.assertEqual(o("#+BEGIN_EXAMPLE\nbody\n#+END_EXAMPLE"),
                         "<p>body</p>")

    def test_src_block_inside_list_item(self):
        h = o("- a\n  #+BEGIN_SRC sh\n  ls\n  #+END_SRC\n- b")
        self.assertIn('<li>a<pre><code class="lang-sh">ls</code></pre></li>', h)
        self.assertIn("<li>b</li>", h)

    def test_horizontal_rule(self):
        self.assertEqual(o("-----"), "<hr>")
        self.assertEqual(o("----"), "<p>----</p>")  # 5 個未満は罫線にならない

    def test_table_with_header(self):
        h = o("| 名前 | 数 |\n|------+----|\n| あ   | 1  |\n| い   | 2  |")
        self.assertEqual(
            h, "<table><thead><tr><th>名前</th><th>数</th></tr></thead>"
               "<tbody><tr><td>あ</td><td>1</td></tr>"
               "<tr><td>い</td><td>2</td></tr></tbody></table>")

    def test_table_without_separator_has_no_header(self):
        h = o("| a | b |\n| 1 | 2 |")
        self.assertNotIn("<th>", h)
        self.assertEqual(h.count("<tr>"), 2)

    def test_table_pads_short_rows_and_formats_cells(self):
        h = o("| *a* | b |\n|---+---|\n| 1 |")
        self.assertIn("<th><strong>a</strong></th>", h)
        self.assertIn("<td>1</td><td></td>", h)

    def test_crlf_and_tabs(self):
        self.assertEqual(o("* A\r\n本文\r\n"), "<h1>A</h1>\n<p>本文</p>")
        self.assertEqual(o("- a\n\t- b"),
                         "<ul><li>a<ul><li>b</li></ul></li></ul>")

    def test_empty(self):
        self.assertEqual(o(""), "")
        self.assertEqual(o("\n\n"), "")

    def test_realistic_document(self):
        h = o("#+TITLE: 日記\n* TODO 買い物 :home:\n- [ ] 牛乳\n- [X] 卵\n\n"
              "** メモ\n本文の *太字* と [[https://e.com][リンク]]\n")
        for part in ('<h1 class="title">日記</h1>', '<span class="todo">TODO',
                     "<h2>メモ</h2>", "<strong>太字</strong>",
                     'href="https://e.com"'):
            self.assertIn(part, h)


class Limits(unittest.TestCase):
    def test_unclosed_markers_stay_fast(self):
        for src in ("*a " * 16000, "+a " * 16000, "/a " * 16000,
                    "_a" * 32000, "=a " * 16000):
            t0 = time.perf_counter()
            o(src)
            self.assertLess(time.perf_counter() - t0, 3.0, src[:6])

    def test_unclosed_brackets_stay_fast(self):
        for src in ("[[" * 20000, "[[a" * 20000, "[" * 20000):
            t0 = time.perf_counter()
            o(src)
            self.assertLess(time.perf_counter() - t0, 3.0)

    def test_link_length_limit(self):
        # 上限を超えたら、[[ がそのまま出る
        self.assertTrue(o("[[https://e.com][" + "あ" * 500 + "]]")
                        .startswith("<p><a "))
        self.assertTrue(o("[[https://e.com][" + "あ" * 510 + "]]")
                        .startswith("<p>[["))

    def test_long_runs_of_whitespace_and_stars(self):
        for src in (" " * 50000 + "x", "* " + " " * 50000 + "x",
                    "*" * 50000, "| a |" + " " * 50000, "- " * 20000):
            t0 = time.perf_counter()
            o(src)
            self.assertLess(time.perf_counter() - t0, 3.0)

    def test_deep_nesting_raises_recursion_error_only(self):
        deep = "".join("  " * i + "- x\n" for i in range(3000))
        with self.assertRaises(RecursionError):
            o(deep)


if __name__ == "__main__":
    unittest.main()
