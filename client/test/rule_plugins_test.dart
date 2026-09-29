import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/picks.dart';
import 'package:seven_double_client/src/shell.dart';

RulePluginInfo plugin(String id, {
  bool required = false,
  bool defaultEnabled = false,
  List<String> depends = const [],
}) => RulePluginInfo.fromJson({
  'id': id,
  'name': id,
  'version': 1,
  'description': '$id 的公开说明',
  'category': '规则',
  'required': required,
  'default_enabled': defaultEnabled,
  'depends': depends,
});

void main() {
  testWidgets('插件依赖必须先启用，使用中的依赖不能关闭，必选规则保持开启',
      (tester) async {
    List<String>? result;
    await tester.pumpWidget(MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(body: Builder(builder: (context) => FilledButton(
        onPressed: () async => result = await showRulePluginPicker(context,
          plugins: [
            plugin('必选规则', required: true),
            plugin('依赖规则'),
            plugin('依赖者', depends: ['依赖规则']),
            plugin('默认可选', defaultEnabled: true),
          ],
        ),
        child: const Text('选择插件'),
      ))),
    ));
    await tester.tap(find.text('选择插件'));
    await tester.pumpAndSettle();

    Finder row(String id) => find.widgetWithText(CheckboxListTile, '$id · 1');
    bool enabled(String id) => tester.widget<CheckboxListTile>(row(id)).value!;
    Future<void> toggle(String id) async {
      await tester.ensureVisible(row(id));
      await tester.tap(row(id));
      await tester.pumpAndSettle();
    }

    expect(enabled('必选规则'), isTrue);
    expect(tester.widget<CheckboxListTile>(row('必选规则')).onChanged, isNull);
    expect(enabled('依赖规则'), isFalse);
    expect(enabled('默认可选'), isTrue);
    await toggle('依赖者');
    expect(enabled('依赖者'), isFalse);
    expect(find.text('请先启用依赖：依赖规则'), findsOneWidget);
    await toggle('依赖规则');
    await toggle('依赖者');
    expect(enabled('依赖者'), isTrue);
    await toggle('依赖规则');
    expect(enabled('依赖规则'), isTrue);
    expect(find.textContaining('请先关闭依赖它的插件：依赖者'), findsOneWidget);
    await toggle('依赖者');
    await toggle('依赖规则');
    await tester.tap(find.text('确认插件（2）'));
    await tester.pumpAndSettle();
    expect(result, ['必选规则', '默认可选']);
  });

  testWidgets('默认启用插件缺少依赖时不能确认，启用依赖后才能继续', (tester) async {
    await tester.pumpWidget(MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(body: Builder(builder: (context) => FilledButton(
        onPressed: () => showRulePluginPicker(context, plugins: [
          plugin('依赖规则'),
          plugin('默认规则', defaultEnabled: true, depends: ['依赖规则']),
        ]),
        child: const Text('选择插件'),
      ))),
    ));
    await tester.tap(find.text('选择插件'));
    await tester.pumpAndSettle();
    expect(find.textContaining('默认规则 需要先启用依赖：依赖规则'), findsOneWidget);
    expect(tester.widget<FilledButton>(find.widgetWithText(
        FilledButton, '确认插件（1）')).onPressed, isNull);
    await tester.tap(find.widgetWithText(CheckboxListTile, '依赖规则 · 1'));
    await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(find.widgetWithText(
        FilledButton, '确认插件（2）')).onPressed, isNotNull);
  });

  testWidgets('插件公告显示公开名称、版本和说明，损坏载荷回退原正文', (tester) async {
    GameMessage announcement(Map<String, dynamic>? payload) => GameMessage.fromJson({
      'id': 1,
      'kind': 'alert',
      'text': '原有公告正文',
      'payload': payload,
    });
    Future<void> render(Map<String, dynamic>? payload) => tester.pumpWidget(
      MaterialApp(theme: buildAppTheme(), home: Scaffold(body: MessageBubble(
        message: announcement(payload),
      ))),
    );
    await render({
      'type': 'plugin',
      'id': 'voting',
      'name': '投票平衡',
      'version': 2,
      'description': '傀儡不参与普通投票。',
      'category': '规则',
      'module_path': 'private/server/module.py',
    });
    expect(find.textContaining('投票平衡 · v2'), findsOneWidget);
    expect(find.textContaining('傀儡不参与普通投票。'), findsOneWidget);
    expect(find.textContaining('原有公告正文'), findsNothing);
    expect(find.textContaining('private/server/module.py'), findsNothing);
    await render({'type': 'plugin', 'name': '投票平衡', 'version': 2});
    expect(find.text('原有公告正文'), findsOneWidget);
    await render(null);
    expect(find.text('原有公告正文'), findsOneWidget);
  });
}
