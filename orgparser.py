"""Org-mode -> HTML パーサー（Org の文書を読む・軽く編集するための部分対応）。

標準ライブラリのみ。mdparser と同じく、入力はすべてエスケープし、生の HTML は通さない。
リンクと画像の URL は safe_url() を通す。ファイルは読まない（純粋な関数）。

対応する書き方:
  見出し（* の数が階層、TODO / DONE、行末の :tag:）、段落、
  *太字* /斜体/ _下線_ +取り消し+ =逐語= ~コード~、
  リンク [[URL][説明]] [[URL]]（画像の URL は画像）、素の http(s) URL、
  リスト（- + *、1. 1)、入れ子、[ ] [X] のチェックボックス）、
  #+BEGIN_SRC / #+BEGIN_EXAMPLE / #+BEGIN_QUOTE / #+BEGIN_COMMENT、
  表（|---+---| の区切り行）、水平線（-----）、#+TITLE:、行頭の # のコメント、
  SCHEDULED: / DEADLINE: / CLOSED: の行（目立たない色で表示）、
  ドロワー（:PROPERTIES: は表示しない。ほかの :名前: は、中身だけを表示する）、
  脚注（本文の [fn:ラベル] を、参照された順の番号にして、定義 [fn:ラベル] 本文 を末尾に出す）。
上記以外の #+ で始まる行は表示しない（#+BEGIN_EXPORT などの囲みの行も表示せず、
中身は普通の文として扱う）。#+INCLUDE（別ファイルの取り込み）、インライン脚注
[fn::本文]、説明リスト（- 語 :: 説明）、Babel などは未対応。

Org 本来の規則に合わせているので、強調記号（* / _ + = ~）は、直前が空白か ( { ' " -、
直後が空白か - . , ; : ! ? ' ) } " のときだけ有効になる。日本語の文字や読点のすぐ隣
（「、*太字*、」など）では、Emacs の Org と同じく強調にならない。
"""
import re

from mdparser import esc, safe_url, trim_url

__all__ = ["org_to_html"]

# --- インライン -----------------------------------------------------
# Org の記号の規則：直前が空白か ( { ' " -、直後が空白か - . , ; : ! ? ' ) } " のとき有効。
_PRE = r"(?<![^\s\-({'\">\x00])"
_POST = r"(?![^\s\-.,;:!?')}\"<\x00])"
_MAX = 500  # 強調の中身の最大長（閉じていない記号で処理時間が二乗に増えるのを防ぐ）


def _marker(ch, tag):
    c = re.escape(ch)
    rx = re.compile(_PRE + c + r"(?=\S)([\s\S]{0,%d}?\S)" % (_MAX - 2) + c + _POST)
    return rx, r"<%s>\1</%s>" % (tag, tag)


_MARKS = [_marker("*", "strong"), _marker("/", "em"),
          _marker("_", "u"), _marker("+", "del")]
_CODE = re.compile(_PRE + r"([=~])(?=\S)([^\n]{0,%d}?\S)\1" % _MAX + _POST)
# URL も説明も 500 文字まで。閉じていない [[ が大量にあっても、探索が二乗に増えない
_LINK2 = re.compile(r"\[\[([^\]]{1,500})\]\[([^\]]{1,500})\]\]")
_LINK1 = re.compile(r"\[\[([^\]]{1,500})\]\]")
_FNREF = re.compile(r"\[fn:([\w-]{1,50})\]")
_IMG = re.compile(r"\.(png|jpe?g|gif|svg|webp)\Z", re.I)
_BARE = re.compile(r"(^|[\s(])(https?://[^\s<　-鿿＀-￯]+)")
_HOLD = re.compile(r"\x00(\d+)\x00")
_A = ' target="_blank" rel="noopener noreferrer"'


def _marks(s):
    for rx, rep in _MARKS:
        s = rx.sub(rep, s)
    return s


def _inline(s, fn=None):
    """fn は、脚注のラベルから番号への対応。参照 [fn:ラベル] を番号にする。"""
    s = s.replace("\x00", "")  # プレースホルダの偽造を防ぐ
    stash = []

    def hold(h):
        stash.append(h)
        return "\x00%d\x00" % (len(stash) - 1)

    s = _CODE.sub(lambda m: hold("<code>" + esc(m.group(2)) + "</code>"), s)
    s = esc(s)
    if fn:  # 定義のないラベルは、そのまま文字として残す
        s = _FNREF.sub(lambda m: hold("<sup>%d</sup>" % fn[m.group(1)])
                       if m.group(1) in fn else m.group(0), s)
    s = _LINK2.sub(lambda m: hold(
        '<a href="' + safe_url(m.group(1)) + '"' + _A + ">"
        + _marks(m.group(2)) + "</a>"), s)

    def link1(m):
        u = m.group(1)
        if _IMG.search(u):
            return hold('<img alt="" src="' + safe_url(u) + '">')
        return hold('<a href="' + safe_url(u) + '"' + _A + ">" + u + "</a>")

    s = _LINK1.sub(link1, s)

    def bare(m):
        raw = m.group(2)
        u = trim_url(raw)
        if not re.match(r"https?://[^\s.]", u):
            return m.group(0)
        return (m.group(1) + hold('<a href="' + u + '"' + _A + ">" + u
                                  + "</a>") + raw[len(u):])

    s = _BARE.sub(bare, s)
    s = _marks(s)
    while _HOLD.search(s):
        s = _HOLD.sub(lambda m: stash[int(m.group(1))], s)
    return s


# --- ブロック -------------------------------------------------------
_BEGIN = re.compile(r"^\s*#\+BEGIN_(\w+)(?:\s+(.*?))?\s*\Z", re.I)
_KEYWORD = re.compile(r"^\s*#\+(\w+):?\s*(.*?)\s*\Z")
_COMMENT = re.compile(r"^\s*#(?:\s|\Z)")
_HEAD = re.compile(r"^(\*+)\s+(.*?)\s*\Z")
_HR = re.compile(r"^\s*-{5,}\s*\Z")
_TABLE = re.compile(r"^\s*\|")
_SEP = re.compile(r"^\s*\|[-+]+\|?\s*\Z")
_ITEM = re.compile(r"^(\s*)([-+*]|\d+[.)])\s+(.*)")
_TODO = re.compile(r"^(TODO|DONE)\s+(.*)")
_TAGS = re.compile(r"\s+(:(?:[\w@#%]+:)+)\Z")
_PLAN = re.compile(
    r"^\s*((?:(?:SCHEDULED|DEADLINE|CLOSED):\s*[<\[][^>\]\n]{1,60}[>\]]\s*)+)\Z")
_DRAWER = re.compile(r"^\s*:([\w-]{1,40}):\s*\Z")
_DRAWER_END = re.compile(r"^\s*:END:\s*\Z", re.I)
_FNDEF = re.compile(r"^\[fn:([\w-]{1,50})\]\s*(.*)")
_BLOCKS = ("SRC", "EXAMPLE", "QUOTE", "COMMENT")
_VERBATIM = ("SRC", "EXAMPLE", "COMMENT")  # 中身を解釈しない囲み


def _blank(l):
    return not l.strip()


def _indent(l):
    return len(l) - len(l.lstrip())


def _dedent(lines, n):
    return [x[min(n, _indent(x)):] for x in lines]


def _item(l):
    m = _ITEM.match(l)
    # 行頭の「* 」は見出し。箇条書きの * は字下げされている
    if m and m.group(2) == "*" and not m.group(1):
        return None
    return m


def _block_start(l):
    m = _BEGIN.match(l)
    return m.group(1).upper() if m and m.group(1).upper() in _BLOCKS else None


def _end_index(L, i, kind):
    """#+END_xxx の行の位置。見つからなければ末尾（len(L)）。"""
    end = re.compile(r"^\s*#\+END_%s\s*\Z" % kind, re.I)
    j = i + 1
    while j < len(L) and not end.match(L[j]):
        j += 1
    return j


def _drawer_end(L, i):
    """:END: の行の位置。ドロワーは入れ子にならないので、途中に見出しや別のドロワーの
    始まりがあれば、ドロワーではないとして None を返す（探索は次の候補までで止まる）。"""
    for j in range(i + 1, len(L)):
        if _DRAWER_END.match(L[j]):
            return j
        if _HEAD.match(L[j]) or _DRAWER.match(L[j]):
            return None
    return None


def _drawer_start(L, i):
    """L[i] が、閉じられているドロワーの始まりなら、その :END: の位置。そうでなければ None。"""
    m = _DRAWER.match(L[i])
    if m and m.group(1).upper() != "END":
        return _drawer_end(L, i)
    return None


def _starts_block(l):
    return bool(_blank(l) or _KEYWORD.match(l) or _COMMENT.match(l)
                or _HEAD.match(l) or _HR.match(l) or _TABLE.match(l)
                or _PLAN.match(l) or _item(l))


def _heading(m, fn):
    level = min(len(m.group(1)), 6)
    text, kw, tags = m.group(2), "", ""
    t = _TODO.match(text)
    if t:
        cls = "todo done" if t.group(1) == "DONE" else "todo"
        kw = '<span class="%s">%s</span> ' % (cls, t.group(1))
        text = t.group(2)
    g = _TAGS.search(text)
    if g:
        tags = ' <span class="tag">%s</span>' % esc(g.group(1))
        text = text[:g.start()]
    return "<h%d>%s%s%s</h%d>" % (level, kw, _inline(text, fn), tags, level)


def _cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _table(lines, fn):
    rows = [None if _SEP.match(l) else _cells(l) for l in lines]
    first_sep = next((k for k, r in enumerate(rows) if r is None), None)
    if first_sep:  # 区切り行より上が見出し行
        head, body = rows[:first_sep], rows[first_sep + 1:]
    else:
        head, body = [], rows
    body = [r for r in body if r is not None]
    cols = max([len(r) for r in head + body] or [0])

    def tr(r, tag):
        r = r + [""] * (cols - len(r))
        return "<tr>" + "".join("<%s>%s</%s>" % (tag, _inline(c, fn), tag)
                                for c in r) + "</tr>"

    out = "<table>"
    if head:
        out += "<thead>" + "".join(tr(r, "th") for r in head) + "</thead>"
    return out + "<tbody>" + "".join(tr(r, "td") for r in body) \
        + "</tbody></table>"


def _parse_list(L, i, fn):
    n = len(L)
    first = _item(L[i])
    base = len(first.group(1))
    ordered = first.group(2)[0].isdigit()
    start = int(first.group(2)[:-1]) if ordered else 1
    items = []
    while i < n:
        if _blank(L[i]):
            k = i
            while k < n and _blank(L[k]):
                k += 1
            sm = _item(L[k]) if k < n else None
            if (sm and len(sm.group(1)) == base
                    and sm.group(2)[0].isdigit() == ordered):
                i = k
            else:
                break
        m = _item(L[i])
        if (not m or len(m.group(1)) != base
                or m.group(2)[0].isdigit() != ordered):
            break
        text = m.group(3)
        i += 1
        inner = ""
        while i < n:
            l = L[i]
            if _blank(l):
                k = i
                while k < n and _blank(L[k]):
                    k += 1
                if k < n and _indent(L[k]) > base:
                    i = k
                    continue
                break
            ind = _indent(l)
            if ind <= base:
                break
            kind = _block_start(l)
            if _item(l):
                html, i = _parse_list(L, i, fn)
                inner += html
            elif kind:
                end = min(_end_index(L, i, kind) + 1, n)
                inner += _blocks(_dedent(L[i:end], ind), fn)
                i = end
            elif _TABLE.match(l):
                j = i
                while j < n and _TABLE.match(L[j]) and _indent(L[j]) > base:
                    j += 1
                inner += _blocks(_dedent(L[i:j], ind), fn)
                i = j
            else:
                text += " " + l.strip()
                i += 1
        box = ""
        c = re.match(r"^\[([ Xx-])\]\s+", text)
        if c:  # [-]（一部だけ完了）は、未チェックとして扱う
            box = ('<input type="checkbox" disabled'
                   + (" checked" if c.group(1) in "Xx" else "") + "> ")
            text = text[len(c.group(0)):]
        items.append("<li>" + box + _inline(text, fn) + inner + "</li>")
    tag = "ol" if ordered else "ul"
    attr = ' start="%d"' % start if ordered and start != 1 else ""
    return "<" + tag + attr + ">" + "".join(items) + "</" + tag + ">", i


def _blocks(L, fn):
    n, i, out = len(L), 0, []
    while i < n:
        l = L[i]
        if _blank(l):
            i += 1
            continue
        kind = _block_start(l)
        if kind:
            end = _end_index(L, i, kind)
            body = _dedent(L[i + 1:end], _indent(l))
            i = min(end + 1, n)
            if kind in ("SRC", "EXAMPLE"):
                lang = ""
                if kind == "SRC":
                    words = (_BEGIN.match(l).group(2) or "").split()
                    lang = words[0] if words else ""
                code = "\n".join(re.sub(r"^,(?=\*|#\+)", "", x) for x in body)
                cls = (' class="lang-' + esc(lang) + '"') if lang else ""
                out.append("<pre><code" + cls + ">" + esc(code)
                           + "</code></pre>")
            elif kind == "QUOTE":
                out.append("<blockquote>" + _blocks(body, fn)
                           + "</blockquote>")
            continue  # COMMENT は表示しない
        m = _KEYWORD.match(l)
        if m:  # #+TITLE: だけ表示し、ほかの #+ の行は表示しない
            if m.group(1).upper() == "TITLE" and m.group(2):
                out.append('<h1 class="title">' + _inline(m.group(2), fn)
                           + "</h1>")
            i += 1
            continue
        if _COMMENT.match(l):
            i += 1
            continue
        m = _HEAD.match(l)
        if m:
            out.append(_heading(m, fn))
            i += 1
            continue
        m = _PLAN.match(l)
        if m:
            out.append('<p><span class="tag">' + esc(" ".join(m.group(1).split()))
                       + "</span></p>")
            i += 1
            continue
        j = _drawer_start(L, i)
        if j is not None:
            if _DRAWER.match(l).group(1).upper() != "PROPERTIES":
                inner = _blocks(L[i + 1:j], fn)  # PROPERTIES だけは表示しない
                if inner:
                    out.append(inner)
            i = j + 1
            continue
        if _HR.match(l):
            out.append("<hr>")
            i += 1
            continue
        if _TABLE.match(l):
            j = i
            while j < n and _TABLE.match(L[j]):
                j += 1
            out.append(_table(L[i:j], fn))
            i = j
            continue
        if _item(l):
            html, i = _parse_list(L, i, fn)
            out.append(html)
            continue
        p = [l.strip()]
        i += 1
        while (i < n and not _starts_block(L[i])
               and not _drawer_start(L, i)):  # ドロワーは段落を中断する
            p.append(L[i].strip())
            i += 1
        out.append("<p>" + _inline("\n".join(p), fn) + "</p>")
    return "\n".join(out)


def _footnotes(L):
    """脚注の定義を本文から取り出す。

    戻り値は (定義を除いた本文の行, {ラベル: 定義の本文}, {ラベル: 番号})。
    番号は、本文で参照された順。参照されない定義は、番号を持たず、表示しない。
    SRC / EXAMPLE / COMMENT の中は、脚注として解釈しない。
    """
    body, defs, refs, i, n = [], {}, [], 0, len(L)
    while i < n:
        l = L[i]
        kind = _block_start(l)
        if kind in _VERBATIM:
            end = min(_end_index(L, i, kind) + 1, n)
            body.extend(L[i:end])
            i = end
            continue
        m = _FNDEF.match(l)
        if m:  # 定義は、次の空行・見出し・別の定義まで続く
            text = [m.group(2)]
            i += 1
            while (i < n and not _blank(L[i]) and not _HEAD.match(L[i])
                   and not _FNDEF.match(L[i])):
                text.append(L[i].strip())
                i += 1
            defs.setdefault(m.group(1), " ".join(t for t in text if t))
            continue
        refs.extend(r.group(1) for r in _FNREF.finditer(l))
        body.append(l)
        i += 1
    # 本文の参照を先に、そのあとに、脚注の定義の中にある参照を、番号の順に辿る
    fn, k = {}, 0
    while k < len(refs):
        label = refs[k]
        k += 1
        if label in defs and label not in fn:
            fn[label] = len(fn) + 1
            refs.extend(r.group(1) for r in _FNREF.finditer(defs[label]))
    return body, defs, fn


def org_to_html(src):
    lines = src.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    body, defs, fn = _footnotes([l.expandtabs(8) for l in lines])
    html = _blocks(body, fn)
    if fn:
        items = "".join(
            "<p><sup>%d</sup> %s</p>" % (num, _inline(defs[label], fn))
            for label, num in sorted(fn.items(), key=lambda kv: kv[1]))
        html += '\n<hr>\n<div class="footnotes">' + items + "</div>"
    return html
