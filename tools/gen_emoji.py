"""从 QFace 表情索引导出客户端的静态 QQ 表情。

用法（在项目根目录执行）：
    .venv/Scripts/python.exe tools/gen_emoji.py [QFace 仓库路径]

默认从 `D:/super projec lite/Tal_Napcat/QFace` 读取；换机器时用第一个参数指定。

生成内容：
    client/assets/emoji/qq/<id>.png        经典 275 张 + 超级 50 张静态表情
    client/lib/src/emoji.dart              表情总表、token 切分与输入框控制器

只取静态图：QFace 的 `public/static/s<id>.png` 与 `qq_emoji/<id>/png/<id>.png` 逐字节相同，
后者还夹着 38MB 的 apng 动画与 lottie，因此这里直接摊平的 `static/` 目录。

token 采用 `[/名字]`：名字来自 QFace 的 `QDes`（如 `/微笑`）。纯文本 token 让草稿、
发送、2000 字上限与服务端校验都保持原样，网页端即使不渲染也能读懂原文。

表情图来自 QFace（MIT，https://github.com/koishijs/QFace）。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QFACE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\super projec lite\Tal_Napcat\QFace")
ASSETS = ROOT / "client" / "assets" / "emoji" / "qq"
OUT = ROOT / "client" / "lib" / "src" / "emoji.dart"

TEMPLATE = """// 由 tools/gen_emoji.py 从 QFace 表情索引生成，请勿手改。
// 图片来自 QFace（MIT）的 public/static/s<id>.png，只取经典 275 张与超级 50 张静态图。
import 'package:flutter/material.dart';

/// 一条静态 QQ 表情：[id] 是资源文件名，[name] 同时是 `[/名字]` token 的解析键。
@immutable
class EmojiFace {
  const EmojiFace(this.id, this.name, this.pinyin, this.superFace);

  final String id;
  final String name;

  /// 经典表情的拼音全拼与首字母缩写；超级表情没有官方输入码，为空。
  final List<String> pinyin;
  final bool superFace;

  String get asset => 'assets/emoji/qq/$id.png';
  String get token => '[/$name]';
}

/// 表情总表：经典在前、超级在后，顺序即面板里的展示顺序。
const emojiFaces = <EmojiFace>[
{faces}
];

final _faceByName = <String, EmojiFace>{{
  for (final face in emojiFaces) face.name: face,
}};

final _faceById = <String, EmojiFace>{{
  for (final face in emojiFaces) face.id: face,
}};

/// token 形状：`[/名字]`。只认方括号里没有嵌套括号的短名字。
final _tokenPattern = RegExp(r'\\[/([^\\[\\]]{{1,24}})\\]');

EmojiFace? emojiFaceByName(String name) => _faceByName[name];

EmojiFace? emojiFaceById(String id) => _faceById[id];

bool hasEmojiToken(String text) => _tokenPattern.hasMatch(text);

/// 把正文切成「纯文本 + 表情图」交替的 spans。
/// 只有名字能在总表里查到的 token 才变成图片，正文里恰好写成方括号的内容不会被误伤。
List<InlineSpan> emojiSpans(String text, {{TextStyle? style, double size = 20}}) {{
  final spans = <InlineSpan>[];
  var cursor = 0;
  for (final match in _tokenPattern.allMatches(text)) {{
    final face = _faceByName[match.group(1)];
    if (face == null) continue;
    if (match.start > cursor) {{
      spans.add(TextSpan(text: text.substring(cursor, match.start), style: style));
    }}
    spans.add(
      WidgetSpan(
        alignment: PlaceholderAlignment.middle,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 1),
          child: Image.asset(
            face.asset,
            width: size,
            height: size,
            filterQuality: FilterQuality.medium,
          ),
        ),
      ),
    );
    cursor = match.end;
  }}
  if (cursor == 0) return [TextSpan(text: text, style: style)];
  if (cursor < text.length) {{
    spans.add(TextSpan(text: text.substring(cursor), style: style));
  }}
  return spans;
}}

/// 输入框控制器：把 `[/名字]` 画成内联表情图，内部仍然只保存纯文本 token，
/// 因此草稿、发送、长度限制与服务端校验都与普通文本完全一致。
class EmojiEditingController extends TextEditingController {{
  EmojiEditingController({{super.text}});

  /// 在光标处插入表情；没有有效选区时追加到末尾。
  void insertFace(EmojiFace face) {{
    final token = face.token;
    final selection = this.selection;
    final start = selection.isValid ? selection.start : text.length;
    final end = selection.isValid ? selection.end : text.length;
    value = TextEditingValue(
      text: text.replaceRange(start, end, token),
      selection: TextSelection.collapsed(offset: start + token.length),
    );
  }}

  @override
  TextSpan buildTextSpan({{
    required BuildContext context,
    TextStyle? style,
    required bool withComposing,
  }}) {{
    // 中文输入法组词期间一律退回纯文本：合成区间的下划线不能与表情图混排，
    // 否则拼音候选阶段的光标与候选框会错位。组词结束后表情自然显示出来。
    if (!withComposing && hasEmojiToken(text)) {{
      return TextSpan(style: style, children: emojiSpans(text, style: style));
    }}
    return super.buildTextSpan(
      context: context,
      style: style,
      withComposing: withComposing,
    );
  }}
}}
"""


def load_catalog():
    """返回 (id, 名字, 拼音, 是否超级) 列表，顺序即面板展示顺序。"""
    available = {
        path.stem[1:]: path
        for path in (QFACE / "public" / "static").glob("s*.png")
        if path.stem[1:].isdigit()
    }
    classic = json.loads((QFACE / "lib" / "data.json").read_text(encoding="utf-8"))
    sysface = json.loads(
        (QFACE / "public" / "assets" / "qq_emoji" / "face_config.json").read_text(encoding="utf-8")
    )["sysface"]
    super_ids = json.loads(
        (QFACE / "public" / "assets" / "qq_emoji" / "super_emojiids.json").read_text(encoding="utf-8")
    )["emojiids"]

    by_id = {}
    for item in sysface:
        by_id.setdefault(item["QSid"], item)

    entries = []
    for item in classic:
        assert item["QSid"] in available, f"经典表情缺少图片：{item['QSid']}"
        entries.append((item["QSid"], item["QDes"].lstrip("/"), list(item.get("Input") or []), False))
    for face_id in super_ids:
        item = by_id.get(face_id)
        assert item is not None, f"超级表情缺少名字：{face_id}"
        assert face_id in available, f"超级表情缺少图片：{face_id}"
        entries.append((face_id, item["QDes"].lstrip("/"), [], True))

    names = [entry[1] for entry in entries]
    assert len(names) == len(set(names)), "表情名重复，token 无法唯一解析"
    for _id, name, _pinyin, _super in entries:
        assert name and all(char not in name for char in "[]/"), f"表情名不合法：{name}"
    return entries, available


def main() -> None:
    entries, available = load_catalog()

    ASSETS.mkdir(parents=True, exist_ok=True)
    for old in ASSETS.glob("*.png"):
        old.unlink()
    for face_id, *_ in entries:
        shutil.copyfile(available[face_id], ASSETS / f"{face_id}.png")

    lines = []
    for face_id, name, pinyin, super_face in entries:
        words = ", ".join(f"'{word}'" for word in pinyin)
        lines.append(f"  EmojiFace('{face_id}', '{name}', [{words}], {str(super_face).lower()}),")
    OUT.write_text(TEMPLATE.format(faces="\n".join(lines)), encoding="utf-8")

    classic = sum(1 for entry in entries if not entry[3])
    print(f"经典 {classic} + 超级 {len(entries) - classic} = {len(entries)} 条")
    print(f"图片 -> {ASSETS}（{len(list(ASSETS.glob('*.png')))} 张）")
    print(f"目录 -> {OUT}")


if __name__ == "__main__":
    main()
