import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';

import 'models.dart';
import 'store.dart';

Future<void> showActionForm(
  BuildContext context,
  GameStore store,
  ActionDescriptor action, {
  String? asSeat,
}) async {
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    showDragHandle: true,
    builder: (_) => ActionFormSheet(store: store, action: action, asSeat: asSeat),
  );
}

Future<void> showActionPreview(BuildContext context, ActionDescriptor action) =>
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) => Padding(
        padding: const EdgeInsets.fromLTRB(24, 8, 24, 32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(action.label, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 12),
            Text(action.description.isEmpty ? '此行动没有补充说明。' : action.description),
            if (action.unsupportedReason != null) ...[
              const SizedBox(height: 12),
              Text(
                action.unsupportedReason!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
            const SizedBox(height: 12),
            const Text('预览不会提交；轻触按钮后仍须填写并确认。'),
          ],
        ),
      ),
    );

class ActionFormSheet extends StatefulWidget {
  const ActionFormSheet({
    super.key,
    required this.store,
    required this.action,
    this.asSeat,
  });

  final GameStore store;
  final ActionDescriptor action;
  final String? asSeat;

  @override
  State<ActionFormSheet> createState() => _ActionFormSheetState();
}

class _ActionFormSheetState extends State<ActionFormSheet> {
  final formKey = GlobalKey<FormState>();
  final values = <String, dynamic>{};
  final controllers = <String, TextEditingController>{};
  final drawingKeys = <String, GlobalKey<_DrawingPadState>>{};
  String? error;
  bool submitting = false;

  @override
  void initState() {
    super.initState();
    values.addAll(widget.store.draftFor(widget.action, asSeat: widget.asSeat));
    for (final field in widget.action.fields) {
      if (!values.containsKey(field.name) && field.raw.containsKey('default')) {
        values[field.name] = field.raw['default'];
      }
      if (field.type == 'text' || field.type == 'textarea' || field.type == 'number') {
        controllers[field.name] = TextEditingController(text: values[field.name]?.toString() ?? '');
      } else if (field.type == 'checkbox') {
        values.putIfAbsent(field.name, () => false);
      } else if (field.type == 'multiselect') {
        values[field.name] = List<String>.from(values[field.name] as List? ?? const []);
      } else if (field.type == 'drawing') {
        drawingKeys[field.name] = GlobalKey<_DrawingPadState>();
      }
    }
  }

  @override
  void dispose() {
    for (final controller in controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final unsupported = widget.action.unsupportedReason;
    final bottom = MediaQuery.viewInsetsOf(context).bottom;
    return AnimatedPadding(
      duration: MediaQuery.disableAnimationsOf(context) ? Duration.zero : const Duration(milliseconds: 180),
      padding: EdgeInsets.only(bottom: bottom),
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * .86,
        child: Column(
          children: [
            ListTile(
              title: Text(widget.action.label, style: Theme.of(context).textTheme.titleLarge),
              subtitle: Text(widget.action.description.isEmpty ? '请检查参数后再确认提交。' : widget.action.description),
            ),
            if (unsupported != null)
              MaterialBanner(
                content: Text(unsupported),
                leading: const Icon(Icons.block),
                actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('关闭'))],
              ),
            Expanded(
              child: Form(
                key: formKey,
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
                  children: [
                    for (final field in widget.action.fields) _field(field),
                    if (widget.action.id == 'lobby.order') _orderPreview(),
                    if (error != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 12),
                        child: Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                      ),
                  ],
                ),
              ),
            ),
            SafeArea(
              top: false,
              minimum: const EdgeInsets.all(16),
              child: SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: unsupported != null || submitting || widget.store.writeBusy ? null : review,
                  icon: const Icon(Icons.fact_check_outlined),
                  label: const Text('检查并确认'),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _field(ActionField field) {
    final reason = field.unsupportedReason;
    if (reason != null) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Text(reason, style: TextStyle(color: Theme.of(context).colorScheme.error)),
      );
    }
    switch (field.type) {
      case 'text':
      case 'textarea':
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: TextFormField(
            controller: controllers[field.name],
            minLines: field.type == 'textarea' ? 3 : 1,
            maxLines: field.type == 'textarea' ? 6 : 1,
            maxLength: field.raw['max_length'] as int?,
            decoration: InputDecoration(labelText: field.label),
            validator: (value) {
              final text = value?.trim() ?? '';
              if (field.required && text.isEmpty) return '此项必填';
              final min = field.raw['min_length'];
              if (min is int && text.length < min) return '至少输入 $min 个字符';
              return null;
            },
            onChanged: (value) => _change(field.name, value),
          ),
        );
      case 'number':
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: TextFormField(
            controller: controllers[field.name],
            keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
            decoration: InputDecoration(labelText: field.label),
            validator: (value) {
              if ((value == null || value.isEmpty) && !field.required) return null;
              final number = num.tryParse(value ?? '');
              if (number == null) return '请输入数字';
              final min = field.raw['min'];
              final max = field.raw['max'];
              if (min is num && number < min) return '不能小于 $min';
              if (max is num && number > max) return '不能大于 $max';
              return null;
            },
            onChanged: (value) => _change(field.name, num.tryParse(value) ?? value),
          ),
        );
      case 'select':
        final selected = values[field.name]?.toString();
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: DropdownButtonFormField<String>(
            initialValue: field.options.any((option) => option['value'].toString() == selected) ? selected : null,
            decoration: InputDecoration(labelText: field.label),
            items: [
              for (final option in field.options)
                DropdownMenuItem(value: option['value'].toString(), child: Text(option['label'].toString())),
            ],
            validator: (value) => field.required && value == null ? '请选择一项' : null,
            onChanged: (value) => setState(() => _change(field.name, value)),
          ),
        );
      case 'multiselect':
        final selected = List<String>.from(values[field.name] as List? ?? const []);
        return FormField<List<String>>(
          initialValue: selected,
          validator: (_) {
            final min = field.raw['min'] is int ? field.raw['min'] as int : (field.required ? 1 : 0);
            final max = field.raw['max'];
            if (selected.length < min) return '至少选择 $min 项';
            if (max is int && selected.length > max) return '最多选择 $max 项';
            return null;
          },
          builder: (state) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: InputDecorator(
              decoration: InputDecoration(labelText: field.label, errorText: state.errorText),
              child: Wrap(
                spacing: 8,
                children: [
                  for (final option in field.options)
                    FilterChip(
                      label: Text(option['label'].toString()),
                      selected: selected.contains(option['value'].toString()),
                      onSelected: (enabled) {
                        setState(() {
                          final value = option['value'].toString();
                          enabled ? selected.add(value) : selected.remove(value);
                          values[field.name] = selected;
                          state.didChange(selected);
                          _saveDraft();
                        });
                      },
                    ),
                ],
              ),
            ),
          ),
        );
      case 'checkbox':
        return FormField<bool>(
          initialValue: values[field.name] == true,
          validator: (_) => null,
          builder: (state) => CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(field.label),
            subtitle: state.errorText == null
                ? null
                : Text(state.errorText!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            value: values[field.name] == true,
            onChanged: (value) {
              setState(() {
                values[field.name] = value == true;
                state.didChange(value);
                _saveDraft();
              });
            },
          ),
        );
      case 'drawing':
        return FormField<String>(
          initialValue: values[field.name]?.toString(),
          validator: (_) {
            final retained = values[field.name]?.toString().isNotEmpty == true;
            final drawn = drawingKeys[field.name]!.currentState?.hasDrawing == true;
            return field.required && !retained && !drawn ? '请完成绘制' : null;
          },
          builder: (state) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(field.label, style: Theme.of(context).textTheme.labelLarge),
                const SizedBox(height: 8),
                DrawingPad(key: drawingKeys[field.name]),
                Row(
                  children: [
                    TextButton(
                      onPressed: () {
                        drawingKeys[field.name]!.currentState?.clear();
                        values.remove(field.name);
                        state.didChange(null);
                        _saveDraft();
                      },
                      child: const Text('清除'),
                    ),
                    if (values[field.name] != null) const Text('已保留上次草稿图'),
                  ],
                ),
                if (state.errorText != null)
                  Text(state.errorText!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
            ),
          ),
        );
      default:
        return const SizedBox.shrink();
    }
  }

  Widget _orderPreview() {
    final top = values['top']?.toString();
    final cards = widget.store.view?.self['cards'];
    if (top == null || cards is! List) return const SizedBox.shrink();
    String? other;
    for (final raw in cards) {
      if (raw is Map && raw['id']?.toString() != top) other = raw['id']?.toString();
    }
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.layers_outlined),
      title: Text('上层 $top'),
      subtitle: Text('下层 ${other ?? '由服务器确定'}'),
    );
  }

  void _change(String name, dynamic value) {
    values[name] = value;
    _saveDraft();
  }

  void _saveDraft() {
    widget.store.saveDraft(widget.action, values, asSeat: widget.asSeat);
  }

  Future<void> review() async {
    setState(() => error = null);
    if (formKey.currentState?.validate() != true) return;
    for (final field in widget.action.fields.where((item) => item.type == 'drawing')) {
      final pad = drawingKeys[field.name]!.currentState;
      if (pad?.hasDrawing == true) values[field.name] = await pad!.toDataUri();
    }
    await widget.store.saveDraft(widget.action, values, asSeat: widget.asSeat);
    if (!mounted) return;
    final confirmed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        icon: Icon(
          widget.action.raw['danger'] == true ? Icons.warning_amber_rounded : Icons.fact_check_outlined,
          color: widget.action.raw['danger'] == true ? Theme.of(context).colorScheme.error : null,
        ),
        title: Text('确认${widget.action.label}'),
        content: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                if (widget.action.description.isNotEmpty) Text(widget.action.description),
                const SizedBox(height: 12),
                for (final field in widget.action.fields)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text(field.label),
                    subtitle: Text(_displayValue(field, values[field.name])),
                  ),
                if (widget.action.fields.isEmpty) const Text('此行动没有参数，仍需确认后才会提交。'),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('返回检查')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('确认提交')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    if (Platform.isAndroid) await HapticFeedback.lightImpact();
    setState(() => submitting = true);
    try {
      await widget.store.execute(widget.action, values, asSeat: widget.asSeat);
      if (mounted) Navigator.pop(context);
    } on ApiException catch (failure) {
      if (mounted) {
        setState(() {
          error = failure.isConflict
              ? '${failure.message}。草稿已保留，请检查刷新后的状态并再次确认。'
              : failure.message;
          submitting = false;
        });
      }
    }
  }

  String _displayValue(ActionField field, dynamic value) {
    if (field.type == 'drawing') return value == null ? '未绘制' : '已绘制';
    if (field.type == 'checkbox') return value == true ? '是' : '否';
    if (value is List) {
      return value.map((item) => _optionLabel(field, item.toString())).join('、');
    }
    return _optionLabel(field, value?.toString() ?? '（空）');
  }

  String _optionLabel(ActionField field, String value) {
    for (final option in field.options) {
      if (option['value'].toString() == value) return option['label'].toString();
    }
    return value;
  }
}

class DrawingPad extends StatefulWidget {
  const DrawingPad({super.key});

  @override
  State<DrawingPad> createState() => _DrawingPadState();
}

class _DrawingPadState extends State<DrawingPad> {
  final boundaryKey = GlobalKey();
  final points = <Offset?>[];

  bool get hasDrawing => points.any((point) => point != null);

  void clear() => setState(points.clear);

  Future<String> toDataUri() async {
    final boundary = boundaryKey.currentContext!.findRenderObject()! as RenderRepaintBoundary;
    final image = await boundary.toImage(pixelRatio: 2);
    final data = await image.toByteData(format: ui.ImageByteFormat.png);
    image.dispose();
    return 'data:image/png;base64,${base64Encode(data!.buffer.asUint8List())}';
  }

  @override
  Widget build(BuildContext context) => RepaintBoundary(
        key: boundaryKey,
        child: GestureDetector(
          onPanStart: (event) => _add(event.localPosition),
          onPanUpdate: (event) => _add(event.localPosition),
          onPanEnd: (_) => setState(() => points.add(null)),
          child: Container(
            height: 220,
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surface,
              border: Border.all(color: Theme.of(context).colorScheme.outline),
              borderRadius: BorderRadius.circular(12),
            ),
            child: CustomPaint(painter: _StrokePainter(points, Theme.of(context).colorScheme.onSurface)),
          ),
        ),
      );

  void _add(Offset point) => setState(() => points.add(point));
}

class _StrokePainter extends CustomPainter {
  const _StrokePainter(this.points, this.color);
  final List<Offset?> points;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round;
    for (var index = 0; index < points.length - 1; index++) {
      final from = points[index];
      final to = points[index + 1];
      if (from != null && to != null) canvas.drawLine(from, to, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _StrokePainter oldDelegate) => true;
}
