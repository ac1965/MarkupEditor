# AGENTS.md

`md_editor.py` と `mdparser.py` を改修するエージェント向けの指示書。

## 目的

Windows / macOS / Linux のどれでも動く、Markdown の閲覧・編集エディタ（Python / tkinter）。

## 守る制約

1. **OS 非依存**：OS 固有の API、パス、フォントを前提にしない。OS で分岐してよいのは、ショートカットの修飾キー（⌘ と Ctrl）の切り替えだけ。
2. **XSS 対策を壊さない**：ユーザー入力は必ず `esc()` を通してから HTML にする。リンクと画像の URL は `safe_url()` を通し、`http` / `https` / `mailto` / `tel` と相対パス以外は `#` に置き換える。生の HTML を許可する変更をしない。プレビューのリンクは、`open_link()` で `http` / `https` / `mailto` / `tel` だけを開く。
3. **パーサーは GUI に依存しない**：`mdparser.py` は tkinter に触れない純粋な関数だけにする。
4. **日本語入力を壊さない**：`Enter` や `Tab` を独自に処理する場合は、変換中の入力が壊れないことを実機で確認する（現状は独自処理なし。IME での入力は確認済み）。

## 構成

| ファイル | 役割 |
|---|---|
| `mdparser.py` | `md_to_html(src)`、`export_html(title, src)`。Markdown → HTML |
| `md_editor.py` | tkinter のエディタ本体。`Renderer` が HTML を Text ウィジェットに描き、`App` が UI・ファイル操作・自動保存を持つ |
| `test_mdparser.py` | パーサーの単体テスト |

- ファイルは UTF-8 だけを扱い、BOM と改行コード（LF / CRLF）は開いたファイルのとおりに保存する。
- 下書き・テーマ・表示モードは `~/.md-editor/state.json` に保存する。書き込みに失敗しても例外で止めない。

## 検証手順（変更後に必ず実行）

```bash
python -m unittest test_mdparser
```

- 全件成功すること。パーサーの挙動を変えたら、`test_mdparser.py` にケースを足す。
- GUI（`md_editor.py`）には自動テストがない。変更したら `python md_editor.py` を実際に起動して確認する。

## 既知の制約（仕様として許容している）

- CommonMark には完全準拠していない。未対応は、setext 見出し、インデントコード、リンク参照定義、`<URL>` 形式のオートリンク、HTML 実体参照、末尾 `\` の改行、複数バッククォートのコードスパン、リンクの `'title'` 形式、括弧が 2 段以上入れ子の URL。
- 脚注、数式、Mermaid、シンタックスハイライトは未対応。生の HTML は許可しない。
- プレビューは Text ウィジェットへの描画。画像は `[画像: 代替テキスト]` と表示する。表は縦線を引かず、セル内の太字やリンクは反映しない。
- `Enter` でのリスト継続、`Tab` での字下げは未実装。
- 動作確認は Windows で行った。日本語入力（IME）は確認済み。Linux と macOS は実機で確認していない。

## 変更時のルール

- 機能を足すときは、上の「守る制約」に反しないか先に確認する。反する場合は実装せず、理由を添えて相談する。
- 推測で仕様を決めない。OS やライブラリの挙動など、確認できないことは確認できないと書く。
