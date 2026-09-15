import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/action_sheet.dart';
import 'package:seven_double_client/src/models.dart';

Map<String, dynamic> actionJson(
        {int uiVersion = 1, String fieldType = 'text'}) =>
    {
      'id': 'test.action',
      'ui_version': uiVersion,
      'short_label': '测试',
      'label': '测试行动',
      'description': '只用于协议安全检查',
      'payload': <String, dynamic>{},
      'fields': [
        {'name': 'value', 'label': '值', 'type': fieldType, 'required': true},
      ],
    };

void main() {
  test('accepts exactly the seven supported field types', () {
    for (final type in ActionField.supportedTypes) {
      expect(
          ActionDescriptor.fromJson(actionJson(fieldType: type))
              .unsupportedReason,
          isNull);
    }
    expect(
        ActionDescriptor.fromJson(actionJson(uiVersion: 2)).unsupportedReason,
        isNotNull);
    expect(
        ActionDescriptor.fromJson(actionJson(fieldType: 'remote_widget'))
            .unsupportedReason,
        isNotNull);
  });

  testWidgets('unsupported actions are visibly blocked in preview',
      (tester) async {
    final action =
        ActionDescriptor.fromJson(actionJson(fieldType: 'remote_widget'));
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (context) => TextButton(
          onPressed: () => showActionPreview(context, action),
          child: const Text('预览'),
        ),
      ),
    ));
    await tester.tap(find.text('预览'));
    await tester.pumpAndSettle();
    expect(find.textContaining('客户端版本不支持字段类型'), findsOneWidget);
    expect(find.textContaining('预览不会提交'), findsOneWidget);
  });
}
