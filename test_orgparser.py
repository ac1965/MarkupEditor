import re
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
        self.assertIn('<img alt="a.png" src="./a.png">', o("[[./a.png]]"))

    def test_bare_url_trims_punctuation(self):
        h = o("see https://e.com/a. next")
        self.assertIn('href="https://e.com/a"', h)

    def test_url_with_slashes_is_not_italic(self):
        self.assertNotIn("<em>", o("https://e.com/a/b/c/d"))

    def test_code_marker_inside_url_query(self):
        self.assertNotIn("<code>", o("https://e.com/?a=1&b=2"))


def href(text):
    """text を変換して、最初の href か src の値を返す（無ければ None）。"""
    m = re.search(r'(?:href|src)="([^"]*)"', o(text))
    return m.group(1) if m else None


class FileLinks(unittest.TestCase):
    def test_relative_file_link_keeps_only_the_path(self):
        self.assertEqual(href("[[file:org/core.org][a]]"), "org/core.org")
        self.assertEqual(href("[[file:./x.org][a]]"), "./x.org")
        self.assertEqual(href("[[file:../up.org][a]]"), "../up.org")
        self.assertEqual(href("[[file:a.org]]"), "a.org")

    def test_plain_relative_path_is_also_a_file_link(self):
        self.assertEqual(href("[[./x.org][a]]"), "./x.org")
        self.assertEqual(href("[[x.org][a]]"), "x.org")

    def test_search_option_is_kept(self):
        for link in ("org/personal.org::#personal-config", "a.org::*見出し",
                     "a.org::12", "a.org::検索する文字"):
            self.assertEqual(href("[[file:%s][x]]" % link), link)
        # 拡張子のドットのせいで、スキームと間違えない（a.org: を scheme と見ない）
        self.assertEqual(href("[[a.org::5][x]]"), "a.org::5")

    def test_absolute_and_network_paths_are_neutralised(self):
        for target in ("/etc/passwd", "~/secret", "C:/Windows/x", "c:\\x",
                       "\\\\host\\share", "//host/x"):
            self.assertEqual(href("[[file:%s][x]]" % target), "#", target)

    def test_file_scheme_url_forms_are_neutralised(self):
        self.assertEqual(href("[[file:///etc/passwd][x]]"), "#")
        self.assertEqual(href("[[file://host/share][x]]"), "#")

    def test_dangerous_schemes_stay_neutralised(self):
        for target in ("javascript:alert(1)", "file:javascript:alert(1)",
                       "JaVaScRiPt:x", "data:text/html,x", "vbscript:x"):
            self.assertEqual(href("[[%s][x]]" % target), "#", target)

    def test_search_part_cannot_smuggle_a_scheme(self):
        self.assertEqual(href("[[javascript:alert(1)::x][a]]"), "#")

    def test_web_and_internal_links_are_unchanged(self):
        self.assertEqual(href("[[https://e.com/a?b=1][x]]"), "https://e.com/a?b=1")
        self.assertEqual(href("[[mailto:a@b.co][x]]"), "mailto:a@b.co")
        self.assertEqual(href("[[#custom-id][x]]"), "#custom-id")
        self.assertEqual(href("[[*見出し][x]]"), "*見出し")

    def test_attribute_injection_in_the_search_part_is_escaped(self):
        h = o('[[file:a.org::*x"onclick="y][a]]')
        self.assertNotIn('"onclick', h)
        self.assertIn("&quot;onclick=&quot;", h)

    def test_image_src_follows_the_same_rule(self):
        self.assertEqual(href("[[file:svg/x.svg]]"), "svg/x.svg")
        self.assertEqual(href("[[file:/abs/x.png]]"), "#")
        self.assertEqual(href("[[file:C:/x.png]]"), "#")


class ImageNames(unittest.TestCase):
    def test_alt_is_the_file_name(self):
        for link, alt in (("[[file:svg/tangle-flow.svg]]", "tangle-flow.svg"),
                          ("[[./a.png]]", "a.png"),
                          ("[[file:demo.png]]", "demo.png"),
                          ("[[https://e.com/img/logo.PNG]]", "logo.PNG")):
            self.assertIn('alt="%s"' % alt, o(link), link)

    def test_alt_is_escaped_and_never_leaks_a_path(self):
        h = o("[[file:a/<b>.png]]")
        self.assertIn('alt="&lt;b&gt;.png"', h)
        self.assertNotIn("<b>", h)
        self.assertNotIn("a/", h.split('alt="')[1].split('"')[0])

    def test_dangerous_image_url_keeps_src_neutralised(self):
        h = o("[[javascript:alert(1)//a.png]]")
        self.assertIn('src="#"', h)
        self.assertNotIn("javascript", h)


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
        self.assertEqual(o("#+BEGIN_EXPORT html\nbody\n#+END_EXPORT"),
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


class Planning(unittest.TestCase):
    def test_scheduled_and_deadline_lines(self):
        self.assertEqual(
            o("SCHEDULED: <2024-05-01 Wed> DEADLINE: <2024-05-10 Fri>"),
            '<p><span class="tag">SCHEDULED: &lt;2024-05-01 Wed&gt; '
            "DEADLINE: &lt;2024-05-10 Fri&gt;</span></p>")

    def test_closed_with_inactive_timestamp(self):
        self.assertIn("CLOSED: [2024-05-01 Wed 10:00]",
                      o("CLOSED: [2024-05-01 Wed 10:00]"))

    def test_planning_after_heading_is_not_part_of_a_paragraph(self):
        h = o("* TODO 提出\nDEADLINE: <2024-05-10 Fri>\n本文")
        self.assertEqual(h.count("<p>"), 2)
        self.assertIn("<p>本文</p>", h)

    def test_ordinary_text_with_the_word_is_not_planning(self):
        self.assertNotIn("span", o("DEADLINE: 来週まで"))
        self.assertNotIn("span", o("DEADLINE: <not a date>> x"))

    def test_planning_text_is_escaped(self):
        self.assertNotIn("<script>", o("SCHEDULED: <2024><script>"))


class Drawers(unittest.TestCase):
    def test_properties_drawer_is_hidden(self):
        self.assertEqual(
            o("* 見出し\n:PROPERTIES:\n:ID: abc\n:CUSTOM_ID: x\n:END:\n本文"),
            "<h1>見出し</h1>\n<p>本文</p>")

    def test_drawer_names_are_case_insensitive(self):
        self.assertEqual(o(":properties:\n:ID: a\n:end:"), "")

    def test_other_drawer_shows_only_its_content(self):
        self.assertEqual(
            o(":LOGBOOK:\n- State DONE\n:END:"),
            "<ul><li>State DONE</li></ul>")

    def test_drawer_interrupts_a_paragraph(self):
        self.assertEqual(o("前\n:LOGBOOK:\n中\n:END:\n後"),
                         "<p>前</p>\n<p>中</p>\n<p>後</p>")

    def test_unclosed_drawer_is_plain_text(self):
        self.assertEqual(o(":LOGBOOK:\n中身"), "<p>:LOGBOOK:\n中身</p>")

    def test_drawer_does_not_cross_a_heading(self):
        self.assertEqual(o(":FOO:\n* 見出し\n:END:"),
                         "<p>:FOO:</p>\n<h1>見出し</h1>\n<p>:END:</p>")

    def test_stray_end_and_tag_like_lines_are_text(self):
        self.assertEqual(o(":END:"), "<p>:END:</p>")
        self.assertEqual(o(":foo:\n普通の文"), "<p>:foo:\n普通の文</p>")

    def test_drawer_content_is_escaped(self):
        self.assertIn("&lt;script&gt;", o(":FOO:\n<script>\n:END:"))


class Example(unittest.TestCase):
    def test_example_block_is_verbatim(self):
        self.assertEqual(
            o("#+BEGIN_EXAMPLE\n*生* [[x]] <b>\n#+END_EXAMPLE"),
            "<pre><code>*生* [[x]] &lt;b&gt;</code></pre>")

    def test_example_block_in_list_item(self):
        h = o("- a\n  #+BEGIN_EXAMPLE\n  出力\n  #+END_EXAMPLE")
        self.assertIn("<li>a<pre><code>出力</code></pre></li>", h)


class Footnotes(unittest.TestCase):
    def test_reference_and_definition(self):
        h = o("本文[fn:1]です。\n\n[fn:1] 補足 *強調*")
        self.assertIn("<p>本文<sup>1</sup>です。</p>", h)
        self.assertTrue(h.endswith(
            '<hr>\n<div class="footnotes"><p><sup>1</sup> 補足 '
            "<strong>強調</strong></p></div>"))

    def test_numbered_by_first_reference_not_by_definition(self):
        h = o("[fn:b] 二番目に定義\n[fn:a] 一番目に定義\n\n"
              "先に a [fn:a]、次に b [fn:b]、また a [fn:a]")
        self.assertIn("先に a <sup>1</sup>、次に b <sup>2</sup>、また a "
                      "<sup>1</sup>", h)
        self.assertLess(h.index("<sup>1</sup> 一番目に定義"),
                        h.index("<sup>2</sup> 二番目に定義"))

    def test_unreferenced_definition_is_not_shown(self):
        self.assertEqual(o("本文\n\n[fn:x] 使わない"), "<p>本文</p>")

    def test_undefined_reference_stays_as_text(self):
        self.assertEqual(o("本文 [fn:zzz]"), "<p>本文 [fn:zzz]</p>")

    def test_definition_continues_until_blank_line(self):
        h = o("参照[fn:1]\n\n[fn:1] 一行目\n  二行目\n\n次の段落")
        self.assertIn("<sup>1</sup> 一行目 二行目</p>", h)
        self.assertIn("<p>次の段落</p>", h)

    def test_definition_stops_at_heading_and_next_definition(self):
        h = o("a[fn:1] b[fn:2]\n[fn:1] 一\n[fn:2] 二\n* 見出し")
        self.assertIn("<p><sup>1</sup> 一</p><p><sup>2</sup> 二</p>", h)
        self.assertIn("<h1>見出し</h1>", h)

    def test_reference_in_heading_list_and_table(self):
        h = o("* 見出し[fn:1]\n- 項目[fn:1]\n| 表[fn:1] |\n\n[fn:1] 脚注")
        self.assertEqual(h.count("<sup>1</sup>"), 4)  # 3 つの参照と、定義の番号

    def test_footnotes_inside_code_blocks_are_not_interpreted(self):
        h = o("#+BEGIN_SRC org\n[fn:1] 定義っぽい\n[fn:1]\n#+END_SRC\n\n"
              "本文[fn:1]\n\n[fn:1] 本物")
        self.assertIn("[fn:1] 定義っぽい\n[fn:1]</code>", h)
        self.assertIn("<p>本文<sup>1</sup></p>", h)
        self.assertIn("<sup>1</sup> 本物", h)

    def test_definition_must_start_at_column_zero(self):
        self.assertNotIn("footnotes", o("参照[fn:1]\n\n  [fn:1] 字下げ"))

    def test_footnote_text_is_escaped(self):
        h = o("a[fn:1]\n\n[fn:1] <script>alert(1)</script> [[javascript:x][y]]")
        self.assertNotIn("<script>", h)
        self.assertNotIn("javascript", h)

    def test_reference_inside_footnote_uses_the_same_numbers(self):
        h = o("a[fn:1]\n\n[fn:1] 見よ[fn:2]\n[fn:2] 二")
        self.assertIn("<sup>1</sup> 見よ<sup>2</sup>", h)
        self.assertIn("<p><sup>2</sup> 二</p>", h)

    def test_circular_footnotes_terminate(self):
        h = o("a[fn:1]\n\n[fn:1] 見よ[fn:2]\n[fn:2] 戻る[fn:1]")
        self.assertIn("<sup>1</sup> 見よ<sup>2</sup>", h)
        self.assertIn("<sup>2</sup> 戻る<sup>1</sup>", h)


class Limits(unittest.TestCase):
    def test_unclosed_markers_stay_fast(self):
        for src in ("*a " * 16000, "+a " * 16000, "/a " * 16000,
                    "_a" * 32000, "=a " * 16000):
            t0 = time.perf_counter()
            o(src)
            self.assertLess(time.perf_counter() - t0, 3.0, src[:6])

    def test_drawers_footnotes_and_planning_stay_fast(self):
        n = 20000
        for src in (":a:\n" * n, ":a:\n:END:\n" * (n // 2), ":PROPERTIES:\n" * n,
                    "[fn:1] x\n" * n, "SCHEDULED: <2024-01-01 Mon>\n" * n,
                    "DEADLINE: <" * n,
                    "".join("[fn:%d] 見よ[fn:%d]\n" % (i, i + 1)
                            for i in range(5000)) + "本文[fn:0]"):
            t0 = time.perf_counter()
            o(src)
            self.assertLess(time.perf_counter() - t0, 3.0, src[:12])

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
