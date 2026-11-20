# MD Editor

Python の標準ライブラリ（tkinter）だけで動く Markdown エディタ。Windows / macOS / Linux で使える。
左で書くと、右のプレビューにすぐ反映される。

```
python md_editor.py [ファイル.md]
```

## 画面

左のエディタで書くと、右のプレビューにすぐ反映される。見出し・強調・リスト・引用・表・コードブロックを描き分ける。

| ライト | ダーク |
|---|---|
| ![ライトテーマ](docs/screenshot-light.png) | ![ダークテーマ](docs/screenshot-dark.png) |

## 要件

- Python 3.8 以上（tkinter を含むもの）。Windows と macOS の公式配布版には入っている。
  Debian / Ubuntu 系では `python3-tk` が別パッケージ。
- 外部パッケージ・外部通信は使わない。

## 操作

| 操作 | Windows / Linux | macOS |
|---|---|---|
| 新規 / 開く / 保存 | Ctrl+N / O / S | ⌘N / O / S |
| 名前を付けて保存 | Ctrl+Shift+S | ⌘Shift+S |
| HTML 書き出し | Ctrl+E | ⌘E |
| 文字を大きく / 小さく | Ctrl+`+` / Ctrl+`-` | ⌘`+` / ⌘`-` |

表示メニューで、分割 / エディタのみ / プレビューのみ、ライト / ダークを切り替える。
下書き・テーマ・表示モードは `~/.md-editor/state.json` に保存される。

## 対応する書き方

見出し、段落、強調（`**` `*` `***`）、取り消し線（`~~` `~`）、コード（インライン・フェンス）、
リンク、画像、自動リンク（`https://` `www.` メール）、リスト（入れ子・番号付き・チェックリスト）、
引用、表（列寄せ）、水平線、バックスラッシュのエスケープ。
未対応の構文や制約は `AGENTS.md` の「既知の制約」を参照。

## テスト

```
python -m unittest
```

パーサーのテスト（`test_mdparser.py`）と GUI のテスト（`test_gui.py`）を実行する。
GUI のテストは実際にウィンドウを開く。画面を開けない環境では、自動でスキップされる。
