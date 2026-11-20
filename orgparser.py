"""Org-mode -> HTML パーサー（Org の文書を読む・軽く編集するための部分対応）。

標準ライブラリのみ。mdparser と同じく、入力はすべてエスケープし、生の HTML は通さない。
リンクと画像の URL は safe_url() を通す。

対応する書き方:
  見出し（* の数が階層、TODO / DONE、行末の :tag:）、段落、
  *太字* /斜体/ _下線_ +取り消し+ =逐語= ~コード~、
  リンク [[URL][説明]] [[URL]]（画像の URL は画像）、素の http(s) URL、
  リスト（- + *、1. 1)、入れ子、[ ] [X] のチェックボックス）、
  #+BEGIN_SRC / #+BEGIN_QUOTE / #+BEGIN_COMMENT、表（|---+---| の区切り行）、
  水平線（-----）、#+TITLE:、行頭の # のコメント。
上記以外の #+ で始まる行は表示しない（#+BEGIN_EXAMPLE などの囲みの行も表示せず、
中身は普通の文として扱う）。:PROPERTIES: ドロワー、SCHEDULED / DEADLINE、脚注、
説明リスト（- 語 :: 説明）、Babel などは未対応。

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
_IMG = re.compile(r"\.(png|jpe?g|gif|svg|webp)\Z", re.I)
_BARE = re.compile(r"(^|[\s(])(https?://[^\s<　-鿿＀-￯]+)")
_HOLD = re.compile(r"\x00(\d+)\x00")
_A = ' target="_blank" rel="noopener noreferrer"'


def _marks(s):
    for rx, rep in _MARKS:
        s = rx.sub(rep, s)
    return s


def _inline(s):
    s = s.replace("\x00", "")  # プレースホルダの偽造を防ぐ
    stash = []

    def hold(h):
        stash.append(h)
        return "\x00%d\x00" % (len(stash) - 1)

    s = _CODE.sub(lambda m: hold("<code>" + esc(m.group(2)) + "</code>"), s)
    s = esc(s)
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
_BLOCKS = ("SRC", "QUOTE", "COMMENT")


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


def _starts_block(l):
    return bool(_blank(l) or _KEYWORD.match(l) or _COMMENT.match(l)
                or _HEAD.match(l) or _HR.match(l) or _TABLE.match(l)
                or _item(l))


def _heading(m):
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
    return "<h%d>%s%s%s</h%d>" % (level, kw, _inline(text), tags, level)


def _cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _table(lines):
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
        return "<tr>" + "".join("<%s>%s</%s>" % (tag, _inline(c), tag)
                                for c in r) + "</tr>"

    out = "<table>"
    if head:
        out += "<thead>" + "".join(tr(r, "th") for r in head) + "</thead>"
    return out + "<tbody>" + "".join(tr(r, "td") for r in body) \
        + "</tbody></table>"


def _parse_list(L, i):
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
                html, i = _parse_list(L, i)
                inner += html
            elif kind:
                end = min(_end_index(L, i, kind) + 1, n)
                inner += _blocks(_dedent(L[i:end], ind))
                i = end
            elif _TABLE.match(l):
                j = i
                while j < n and _TABLE.match(L[j]) and _indent(L[j]) > base:
                    j += 1
                inner += _blocks(_dedent(L[i:j], ind))
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
        items.append("<li>" + box + _inline(text) + inner + "</li>")
    tag = "ol" if ordered else "ul"
    attr = ' start="%d"' % start if ordered and start != 1 else ""
    return "<" + tag + attr + ">" + "".join(items) + "</" + tag + ">", i


def _blocks(L):
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
            if kind == "SRC":
                lang = (_BEGIN.match(l).group(2) or "").split()
                lang = lang[0] if lang else ""
                code = "\n".join(re.sub(r"^,(?=\*|#\+)", "", x) for x in body)
                cls = (' class="lang-' + esc(lang) + '"') if lang else ""
                out.append("<pre><code" + cls + ">" + esc(code)
                           + "</code></pre>")
            elif kind == "QUOTE":
                out.append("<blockquote>" + _blocks(body) + "</blockquote>")
            continue  # COMMENT は表示しない
        m = _KEYWORD.match(l)
        if m:  # #+TITLE: だけ表示し、ほかの #+ の行は表示しない
            if m.group(1).upper() == "TITLE" and m.group(2):
                out.append('<h1 class="title">' + _inline(m.group(2))
                           + "</h1>")
            i += 1
            continue
        if _COMMENT.match(l):
            i += 1
            continue
        m = _HEAD.match(l)
        if m:
            out.append(_heading(m))
            i += 1
            continue
        if _HR.match(l):
            out.append("<hr>")
            i += 1
            continue
        if _TABLE.match(l):
            j = i
            while j < n and _TABLE.match(L[j]):
                j += 1
            out.append(_table(L[i:j]))
            i = j
            continue
        if _item(l):
            html, i = _parse_list(L, i)
            out.append(html)
            continue
        p = [l.strip()]
        i += 1
        while i < n and not _starts_block(L[i]):
            p.append(L[i].strip())
            i += 1
        out.append("<p>" + _inline("\n".join(p)) + "</p>")
    return "\n".join(out)


def org_to_html(src):
    lines = src.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return _blocks([l.expandtabs(8) for l in lines])
