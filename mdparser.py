"""Markdown -> HTML パーサー。

標準ライブラリのみ。GUI にも OS にも依存しない純粋な関数群。
esc() / safe_url() / trim_url() は、orgparser.py も使う。
入力はすべてエスケープし、生の HTML は通さない。リンクと画像の URL は
safe_url() を通し、http / https / mailto / tel と相対パス以外は '#' にする。
"""
import re

__all__ = ["md_to_html", "esc", "safe_url", "trim_url", "export_html"]

# 単語を作る文字。Unicode の \w ではなく ASCII だけにして、
# 日本語の文字のすぐ隣でも _ の強調が効くようにする（日本語_強調_です）
_W = "A-Za-z0-9_"


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


_SCHEME = re.compile(r"^([a-z][a-z0-9+.\-]*):", re.I)
_OK_SCHEME = re.compile(r"(https?|mailto|tel)", re.I)


def safe_url(u):
    u = u.strip()
    m = _SCHEME.match(u)
    if m and not _OK_SCHEME.fullmatch(m.group(1)):
        return "#"
    return u


# 強調の中身の最大長。閉じていない記号が多い長文で、探索が二乗に増えるのを防ぐ。
# これより長い強調は強調にならず、記号がそのまま表示される。
_EMPH_MAX = 500
_ANY = r"[\s\S]{0,%d}?" % _EMPH_MAX
_LINE = r"[^*\n]{0,%d}?" % _EMPH_MAX
_LINE_U = r"[^_\n]{0,%d}?" % _EMPH_MAX

_EMPH = [
    (re.compile(r"\*\*\*(?=\S)(" + _ANY + r"\S)\*\*\*"),
     r"<strong><em>\1</em></strong>"),
    (re.compile(r"(^|[^%s])___(?=\S)(%s\S)___(?![%s])" % (_W, _ANY, _W)),
     r"\1<strong><em>\2</em></strong>"),
    (re.compile(r"\*\*(?=\S)(" + _ANY + r"\S)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(^|[^%s])__(?=\S)(%s\S)__(?![%s])" % (_W, _ANY, _W)),
     r"\1<strong>\2</strong>"),
    (re.compile(r"\*(?=\S)(" + _LINE + r"\S)\*"), r"<em>\1</em>"),
    (re.compile(r"(^|[^%s])_(?=\S)(%s\S)_(?![%s])" % (_W, _LINE_U, _W)),
     r"\1<em>\2</em>"),
    (re.compile(r"(~{1,2})(?=[^\s~])(" + _ANY + r"[^\s~])\1(?!~)"),
     r"<del>\2</del>"),
]


def _emph(s):
    for rx, rep in _EMPH:
        s = rx.sub(rep, s)
    return s


def trim_url(u):
    """URL の末尾にくっついた句読点や、対応のない閉じ括弧を取り除く。"""
    m = re.search(r"&(?:lt|gt|quot);", u)
    if m:
        u = u[:m.start()]
    while True:
        c = u[-1:]
        if c and c in "?!.,:;*_~'":
            u = u[:-1]
        elif c == ")" and u.count(")") > u.count("("):
            u = u[:-1]
        else:
            break
    return u


_CODE = re.compile(r"`([^`\n]+)`")
_BSLASH = re.compile(r"\\([!-/:-@\[-`{-~])")
_URL = r"((?:[^()\s]|\([^()\s]*\))+)"
_TITLE = r"(?:\s+&quot;([^&]*)&quot;)?"
# リンク文字・代替テキストの最大長。閉じ括弧のない [ が大量にあっても、探索が二乗に増えない
_IMG = re.compile(r"!\[([^\]]{0,500})\]\(" + _URL + _TITLE + r"\)")
_LINK = re.compile(r"\[([^\]]{1,500})\]\(" + _URL + _TITLE + r"\)")
_AUTOLINK = re.compile(
    r"(^|[\s(*_~])((?:https?://|www\.)[^\s<\u3000-\u9fff\uff00-\uffef]+)")
_EMAIL = re.compile(
    r"(^|[\s(*_~])([A-Za-z0-9._+\-]{1,64}@[A-Za-z0-9\-]+"  # ローカル部は 64 文字まで
    r"(?:\.[A-Za-z0-9\-]*[A-Za-z0-9])+)")
_HOLD = re.compile(r"\x00(\d+)\x00")


def inline(s):
    s = s.replace("\x00", "")  # プレースホルダの偽造を防ぐ
    stash = []

    def hold(h):
        stash.append(h)
        return "\x00%d\x00" % (len(stash) - 1)

    s = _CODE.sub(lambda m: hold("<code>" + esc(m.group(1)) + "</code>"), s)
    s = _BSLASH.sub(lambda m: hold(esc(m.group(1))), s)
    s = esc(s)

    def img(m):
        a, u, t = m.group(1), m.group(2), m.group(3)
        return hold('<img alt="' + a + '" src="' + safe_url(u) + '"'
                    + (' title="' + t + '"' if t else "") + ">")

    def link(m):
        a, u, t = m.group(1), m.group(2), m.group(3)
        return hold('<a href="' + safe_url(u)
                    + '" target="_blank" rel="noopener noreferrer"'
                    + (' title="' + t + '"' if t else "") + ">"
                    + _emph(a) + "</a>")

    def auto(m):
        p, raw = m.group(1), m.group(2)
        u = trim_url(raw)
        if not re.match(r"(https?://|www\.)[^\s.]", u):
            return m.group(0)
        href = "http://" + u if u.startswith("www.") else u
        return (p + hold('<a href="' + href
                         + '" target="_blank" rel="noopener noreferrer">'
                         + u + "</a>") + raw[len(u):])

    def mail(m):
        return m.group(1) + hold(
            '<a href="mailto:' + m.group(2) + '">' + m.group(2) + "</a>")

    s = _IMG.sub(img, s)
    s = _LINK.sub(link, s)
    s = _AUTOLINK.sub(auto, s)
    s = _EMAIL.sub(mail, s)
    s = _emph(s)
    s = re.sub(r"(?<! ) {2,}\n", "<br>", s)  # 空白の列の先頭からだけ試す
    while _HOLD.search(s):
        s = _HOLD.sub(lambda m: stash[int(m.group(1))], s)
    return s


def _split_cells(line):
    line = line.strip()
    line = re.sub(r"^\|", "", line)
    line = re.sub(r"\|\Z", "", line)
    out, cur, k = [], "", 0
    while k < len(line):
        c = line[k]
        if c == "\\" and line[k + 1:k + 2] == "|":
            cur += "|"
            k += 1
        elif c == "|":
            out.append(cur.strip())
            cur = ""
        else:
            cur += c
        k += 1
    out.append(cur.strip())
    return out


_LI = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+")
_HR = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*\Z")
_BLANK = re.compile(r"^\s*\Z")
_SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*\Z")
_H = re.compile(r"^ {0,3}#{1,6}\s")
_FENCE_START = re.compile(r"^\s*(```|~~~)")
_QUOTE = re.compile(r"^\s*>")


def _is_blank(l):
    return _BLANK.match(l) is not None


def _is_table_sep(l):
    return l is not None and "|" in l and "-" in l and _SEP.match(l) is not None


def _starts_block(l, nx):
    return bool(_is_blank(l) or _H.match(l) or _FENCE_START.match(l)
                or _HR.match(l) or _QUOTE.match(l) or _LI.match(l)
                or ("|" in l and _is_table_sep(nx)))


def _fence_close_re(f):
    ch = "`" if f[0] == "`" else "~"
    return re.compile(r"^\s*" + ch + "{" + str(len(f)) + r",}\s*\Z")


def _indent(l):
    return len(re.match(r"\s*", l).group(0))


def _at(L, i):
    return L[i] if 0 <= i < len(L) else None


def _parse_list(L, i):
    n = len(L)
    first = _LI.match(L[i])
    base = len(first.group(1))
    ordered = re.search(r"\d", first.group(2)) is not None
    start_no = int(first.group(2)[:-1]) if ordered else 1
    items, loose = [], False
    while i < n:
        if _is_blank(L[i]):
            k = i
            while k < n and _is_blank(L[k]):
                k += 1
            sm = _LI.match(L[k]) if k < n else None
            if (sm and len(sm.group(1)) == base
                    and (re.search(r"\d", sm.group(2)) is not None) == ordered):
                loose = True
                i = k
            else:
                break
        mm = _LI.match(L[i])
        if (not mm or len(mm.group(1)) != base
                or (re.search(r"\d", mm.group(2)) is not None) != ordered):
            break
        text = L[i][len(mm.group(0)):]
        i += 1
        inner = ""
        while i < n:
            l = L[i]
            if _is_blank(l):
                j = i
                while j < n and _is_blank(L[j]):
                    j += 1
                if j >= n:
                    break
                nl = L[j]
                nm = _LI.match(nl)
                if _indent(nl) > base and (
                        nm or re.match(r"^\s*(```|~~~|>)", nl)):
                    loose = True
                    i = j
                    continue
                break
            m2 = _LI.match(l)
            ind = _indent(l)
            if ind <= base:
                break
            if m2:
                html, i = _parse_list(L, i)
                inner += html
            elif _FENCE_START.match(l):
                cr = _fence_close_re(
                    re.match(r"(`{3,}|~{3,})", l.strip()).group(1))
                sub = [l]
                i += 1
                while i < n:
                    sub.append(L[i])
                    closed = cr.match(L[i]) is not None
                    i += 1
                    if closed:
                        break
                inner += _blocks("\n".join(
                    x[min(ind, _indent(x)):] for x in sub))
            elif _QUOTE.match(l):
                qs = []
                while i < n and _QUOTE.match(L[i]) and _indent(L[i]) > base:
                    qs.append(L[i][min(ind, _indent(L[i])):])
                    i += 1
                inner += _blocks("\n".join(qs))
            else:
                text += " " + l.strip()
                i += 1
        box = ""
        t = re.match(r"^\[([ xX])\]\s+", text)
        if t:
            box = ('<input type="checkbox" disabled'
                   + (" checked" if t.group(1) != " " else "") + "> ")
            text = text[len(t.group(0)):]
        items.append((box, text, inner))
    html = "".join(
        "<li>" + box + ("<p>" + inline(text) + "</p>" if loose
                        else inline(text)) + inner + "</li>"
        for box, text, inner in items)
    tag = "ol" if ordered else "ul"
    attr = ' start="%d"' % start_no if ordered and start_no != 1 else ""
    return "<" + tag + attr + ">" + html + "</" + tag + ">", i


def _blocks(src):
    L = [re.sub(r"^\t+", lambda t: "    " * len(t.group(0)), l)
         for l in re.sub(r"\r\n?", "\n", src).split("\n")]
    n, i, out = len(L), 0, []
    while i < n:
        l = L[i]
        if _is_blank(l):
            i += 1
            continue
        m = re.match(r"^\s*(```+|~~~+)\s*([A-Za-z0-9_+\-]*)", l)
        if m:
            close = _fence_close_re(m.group(1))
            code = []
            i += 1
            while i < n and not close.match(L[i]):
                code.append(L[i])
                i += 1
            i += 1
            cls = ' class="lang-' + esc(m.group(2)) + '"' if m.group(2) else ""
            out.append("<pre><code" + cls + ">" + esc("\n".join(code))
                       + "</code></pre>")
            continue
        m = re.match(r"^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*\Z", l)
        if m:
            k = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (k, inline(m.group(2)), k))
            i += 1
            continue
        if _HR.match(l):
            out.append("<hr>")
            i += 1
            continue
        if _QUOTE.match(l):
            q = []
            while i < n and _QUOTE.match(L[i]):
                q.append(re.sub(r"^\s*> ?", "", L[i], count=1))
                i += 1
                while (i < n and not _QUOTE.match(L[i])
                       and not _starts_block(L[i], _at(L, i + 1))
                       and re.search(r"\S", q[-1])
                       and not re.match(r"^\s*(```|~~~|#{1,6}\s)", q[-1])
                       and not _HR.match(q[-1])):
                    q.append(L[i])
                    i += 1
            out.append("<blockquote>" + _blocks("\n".join(q))
                       + "</blockquote>")
            continue
        if _LI.match(l):
            html, i = _parse_list(L, i)
            out.append(html)
            continue
        if "|" in l and i + 1 < n and _is_table_sep(L[i + 1]):
            head = _split_cells(l)
            al = []
            for c in _split_cells(L[i + 1]):
                if re.match(r"^:-+:\Z", c):
                    al.append("center")
                elif re.search(r"-:\Z", c):
                    al.append("right")
                elif re.match(r"^:-", c):
                    al.append("left")
                else:
                    al.append("")
            i += 2

            def style(k):
                a = al[k] if k < len(al) else ""
                return ' style="text-align:' + a + '"' if a else ""

            h = ("<table><thead><tr>"
                 + "".join("<th" + style(k) + ">" + inline(c) + "</th>"
                           for k, c in enumerate(head))
                 + "</tr></thead><tbody>")
            while i < n and "|" in L[i] and not _is_blank(L[i]):
                cs = _split_cells(L[i])
                h += ("<tr>" + "".join(
                    "<td" + style(k) + ">"
                    + inline(cs[k] if k < len(cs) else "") + "</td>"
                    for k in range(len(head))) + "</tr>")
                i += 1
            out.append(h + "</tbody></table>")
            continue
        p = [l]
        i += 1
        while i < n and not _starts_block(L[i], _at(L, i + 1)):
            p.append(L[i])
            i += 1
        out.append("<p>" + inline("\n".join(p)) + "</p>")
    return "\n".join(out)


def md_to_html(src):
    return _blocks(src)


_EXPORT_CSS = """
body{margin:0;background:#fff;color:#1f2328;font:16px/1.7 system-ui,-apple-system,"Segoe UI","Hiragino Sans","Yu Gothic UI","Noto Sans CJK JP",sans-serif}
.md{max-width:820px;margin:0 auto;padding:24px 16px}
.md h1,.md h2{border-bottom:1px solid #d0d7de;padding-bottom:.3em}
.md code{background:#f0f2f5;padding:.1em .35em;border-radius:4px;font-family:ui-monospace,Menlo,Consolas,monospace}
.md pre{background:#f6f8fa;padding:12px 14px;border-radius:6px;overflow:auto}
.md pre code{background:none;padding:0}
.md blockquote{margin:0;padding:0 1em;color:#57606a;border-left:4px solid #d0d7de}
.md table{border-collapse:collapse}
.md th,.md td{border:1px solid #d0d7de;padding:6px 12px}
.md a{color:#0b57d0}
.md img{max-width:100%}
"""


def export_html(title, src):
    """単体で開ける HTML 文書として書き出す。外部リソースは使わない。"""
    return ('<!doctype html>\n<html lang="ja"><head><meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            "<title>" + esc(title) + "</title>\n<style>" + _EXPORT_CSS
            + '</style></head>\n<body><main class="md">\n'
            + md_to_html(src) + "\n</main></body></html>\n")
