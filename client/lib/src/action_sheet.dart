import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';

import 'app_icons.dart';
import 'design.dart';
import 'models.dart';
import 'picks.dart';
import 'role_visuals.dart';
import 'store.dart';

/// 行动表单：图标 + 短名标题、完整说明、参数、二次确认。
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
    builder: (_) => ActionFormSheet(store: store, action: action, asSeat: asSeat),
  );
}

/// 轻预览：长按行动按钮时展示，不提交。
Future<void> showActionPreview(BuildContext context, ActionDescriptor action) =>
    showModalBottomSheet<void>(
      context: context,
      builder: (context) => Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.xl,
          0,
          AppSpacing.xl,
          AppSpacing.xxl,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                ActionIconBadge(
                  actionId: action.id,
                  group: action.group,
                  danger: action.raw['danger'] == true,
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        action.label,
                        style: const TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w600,
                          color: AppColors.text,
                        ),
                      ),
                      Text(
                        '短名：${action.shortLabel} · ${action.group}',
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppColors.textTertiary,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.lg),
            Text(
              action.description.isEmpty ? '此行动没有补充说明。' : action.description,
              style: const TextStyle(
                fontSize: 14,
                height: 1.6,
                color: AppColors.textSecondary,
              ),
            ),
            if (action.unsupportedReason != null) ...[
              const SizedBox(height: AppSpacing.md),
              Text(
                action.unsupportedReason!,
                style: const TextStyle(color: AppColors.danger, fontSize: 13),
              ),
            ],
            const SizedBox(height: AppSpacing.lg),
            const Text(
              '预览不会提交；点击行动按钮后仍需填写参数并确认。',
              style: TextStyle(fontSize: 12, color: AppColors.textTertiary),
            ),
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
      if (!values.containsKey(field.name) &&
          field.raw.containsKey('default')) {
        values[field.name] = field.raw['default'];
      }
      switch (field.type) {
        case 'text':
        case 'textarea':
        case 'number':
          controllers[field.name] = TextEditingController(
            text: values[field.name]?.toString() ?? '',
          );
        case 'checkbox':
          values.putIfAbsent(field.name, () => false);
        case 'multiselect':
          values[field.name] = List<String>.from(
            values[field.name] as List? ?? const [],
          );
        case 'drawing':
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

  /// 玩家类字段：用自绘选择器（头像 + 名字 + 角色）。
  bool _isPlayerField(ActionField field) =>
      field.name == 'participant_id' || field.name == 'participant_ids';

  bool _isCodexField(ActionField field) =>
      field.name == 'roles' && field.options.length > 11;

  @override
  Widget build(BuildContext context) {
    final action = widget.action;
    final unsupported = action.unsupportedReason;
    final bottom = MediaQuery.viewInsetsOf(context).bottom;
    final danger = action.raw['danger'] == true;
    return AnimatedPadding(
      duration: MediaQuery.disableAnimationsOf(context)
          ? Duration.zero
          : const Duration(milliseconds: 180),
      padding: EdgeInsets.only(bottom: bottom),
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * .88,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.xl,
                0,
                AppSpacing.xl,
                AppSpacing.md,
              ),
              child: Row(
                children: [
                  ActionIconBadge(
                    actionId: action.id,
                    group: action.group,
                    danger: danger,
                    size: 48,
                  ),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Text(
                              action.shortLabel,
                              style: TextStyle(
                                fontSize: 20,
                                fontWeight: FontWeight.w700,
                                color: danger
                                    ? AppColors.danger
                                    : AppColors.text,
                              ),
                            ),
                            const SizedBox(width: AppSpacing.sm),
                            Tag(
                              action.group,
                              color: AppColors.textSecondary,
                              background: AppColors.surfaceMuted,
                            ),
                          ],
                        ),
                        const SizedBox(height: 2),
                        Text(
                          action.description.isEmpty
                              ? action.label
                              : action.description,
                          style: const TextStyle(
                            fontSize: 13,
                            height: 1.5,
                            color: AppColors.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            if (unsupported != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(AppSpacing.md),
                  decoration: BoxDecoration(
                    color: AppColors.dangerSoft,
                    borderRadius: BorderRadius.circular(AppRadius.field),
                  ),
                  child: Row(
                    children: [
                      const Icon(
                        Icons.block,
                        size: 18,
                        color: AppColors.danger,
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: Text(
                          unsupported,
                          style: const TextStyle(
                            fontSize: 13,
                            color: AppColors.danger,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            Expanded(
              child: Form(
                key: formKey,
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(
                    AppSpacing.xl,
                    AppSpacing.sm,
                    AppSpacing.xl,
                    AppSpacing.lg,
                  ),
                  children: [
                    for (final field in action.fields) _field(field),
                    if (action.id == 'lobby.order') _orderPreview(),
                    if (error != null)
                      Padding(
                        padding: const EdgeInsets.only(top: AppSpacing.md),
                        child: Text(
                          error!,
                          style: const TextStyle(
                            color: AppColors.danger,
                            fontSize: 13,
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.xl,
                0,
                AppSpacing.xl,
                AppSpacing.md,
              ),
              child: SafeArea(
                top: false,
                child: SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed:
                        unsupported != null ||
                            submitting ||
                            widget.store.writeBusy
                        ? null
                        : review,
                    style: danger
                        ? FilledButton.styleFrom(
                            backgroundColor: AppColors.danger,
                          )
                        : null,
                    icon: Icon(
                      danger
                          ? Icons.warning_amber_rounded
                          : Icons.fact_check_outlined,
                      size: 18,
                    ),
                    label: const Text('检查并确认'),
                  ),
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
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
        child: Text(reason, style: const TextStyle(color: AppColors.danger)),
      );
    }
    if (_isPlayerField(field)) {
      return _playerField(field);
    }
    if (_isCodexField(field)) {
      return _codexField(field);
    }
    if (field.type == 'select') {
      return _selectField(field);
    }
    if (field.type == 'multiselect') {
      return _multiField(field);
    }

    switch (field.type) {
      case 'text':
      case 'textarea':
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
          child: TextFormField(
            controller: controllers[field.name],
            minLines: field.type == 'textarea' ? 3 : 1,
            maxLines: field.type == 'textarea' ? 6 : 1,
            decoration: InputDecoration(
              labelText: field.label,
              alignLabelWithHint: field.type == 'textarea',
            ),
            validator: (value) {
              final text = value?.trim() ?? '';
              if (field.required && text.isEmpty) {
                return '此项必填';
              }
              final min = field.raw['min_length'];
              if (min is int && text.length < min) {
                return '至少输入 $min 个字符';
              }
              return null;
            },
            onChanged: (value) => _change(field.name, value),
          ),
        );
      case 'number':
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
          child: TextFormField(
            controller: controllers[field.name],
            keyboardType: const TextInputType.numberWithOptions(
              decimal: true,
              signed: true,
            ),
            decoration: InputDecoration(labelText: field.label),
            validator: (value) {
              if ((value == null || value.isEmpty) && !field.required) {
                return null;
              }
              final number = num.tryParse(value ?? '');
              if (number == null) {
                return '请输入数字';
              }
              final min = field.raw['min'];
              final max = field.raw['max'];
              if (min is num && number < min) {
                return '不能小于 $min';
              }
              if (max is num && number > max) {
                return '不能大于 $max';
              }
              return null;
            },
            onChanged: (value) =>
                _change(field.name, num.tryParse(value) ?? value),
          ),
        );
      case 'checkbox':
        final checked = values[field.name] == true;
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
          child: Material(
            color: checked ? AppColors.accentSoft : AppColors.surface,
            borderRadius: BorderRadius.circular(AppRadius.field),
            child: InkWell(
              borderRadius: BorderRadius.circular(AppRadius.field),
              onTap: () => setState(() {
                values[field.name] = !checked;
                _saveDraft();
              }),
              child: Container(
                padding: const EdgeInsets.all(AppSpacing.md),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(AppRadius.field),
                  border: Border.all(
                    color: checked ? AppColors.accent : AppColors.border,
                  ),
                ),
                child: Row(
                  children: [
                    Icon(
                      checked
                          ? Icons.check_box
                          : Icons.check_box_outline_blank,
                      color: checked
                          ? AppColors.accent
                          : AppColors.textTertiary,
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: Text(
                        field.label,
                        style: const TextStyle(
                          fontSize: 14,
                          color: AppColors.text,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        );
      case 'drawing':
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
          child: FormField<String>(
            initialValue: values[field.name]?.toString(),
            validator: (_) {
              final retained =
                  values[field.name]?.toString().isNotEmpty == true;
              final drawn =
                  drawingKeys[field.name]!.currentState?.hasDrawing == true;
              return field.required && !retained && !drawn ? '请完成绘制' : null;
            },
            builder: (state) => Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(
                      Icons.brush_outlined,
                      size: 18,
                      color: AppColors.textSecondary,
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Text(
                        field.label,
                        style: const TextStyle(
                          fontSize: 14,
                          color: AppColors.text,
                        ),
                      ),
                    ),
                    if (values[field.name] != null)
                      const Tag(
                        '已保留上次草稿',
                        color: AppColors.textSecondary,
                        background: AppColors.surfaceMuted,
                      ),
                  ],
                ),
                const SizedBox(height: AppSpacing.sm),
                DrawingPad(key: drawingKeys[field.name]),
                Row(
                  children: [
                    TextButton.icon(
                      onPressed: () {
                        drawingKeys[field.name]!.currentState?.clear();
                        values.remove(field.name);
                        state.didChange(null);
                        _saveDraft();
                      },
                      icon: const Icon(Icons.delete_outline, size: 16),
                      label: const Text('清除'),
                    ),
                  ],
                ),
                if (state.errorText != null)
                  Text(
                    state.errorText!,
                    style: const TextStyle(
                      color: AppColors.danger,
                      fontSize: 12,
                    ),
                  ),
              ],
            ),
          ),
        );
      default:
        return const SizedBox.shrink();
    }
  }

  /// 选玩家：头像 + 名字 + 角色。
  Widget _playerField(ActionField field) {
    final multi = field.type == 'multiselect';
    final selected = multi
        ? List<String>.from(values[field.name] as List? ?? const [])
        : (values[field.name] == null
              ? <String>[]
              : [values[field.name].toString()]);
    final players = playersFromOptions(
      field.options,
      seats: widget.store.view?.seats,
    );
    final picked = players
        .where((player) => selected.contains(player.id))
        .toList();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            field.label,
            style: const TextStyle(
              fontSize: 13,
              color: AppColors.textSecondary,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Material(
            color: AppColors.surfaceMuted,
            borderRadius: BorderRadius.circular(AppRadius.field),
            child: InkWell(
              borderRadius: BorderRadius.circular(AppRadius.field),
              onTap: field.options.isEmpty
                  ? null
                  : () async {
                      final result = await showPlayerPicker(
                        context,
                        title: field.label,
                        subtitle: multi ? '可多选' : '选择一名参与者',
                        players: players,
                        selected: selected,
                        multi: multi,
                        max: multi && field.raw['max'] is int
                            ? field.raw['max'] as int
                            : null,
                      );
                      if (result == null) {
                        return;
                      }
                      setState(() {
                        values[field.name] = multi ? result : result.first;
                        _saveDraft();
                      });
                    },
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.all(AppSpacing.md),
                child: field.options.isEmpty
                    ? const Text(
                        '当前没有可选参与者',
                        style: TextStyle(color: AppColors.textTertiary),
                      )
                    : picked.isEmpty
                    ? Row(
                        children: [
                          const Icon(
                            Icons.person_add_alt,
                            size: 18,
                            color: AppColors.textTertiary,
                          ),
                          const SizedBox(width: AppSpacing.sm),
                          Text(
                            multi ? '点击选择成员' : '点击选择参与者',
                            style: const TextStyle(
                              color: AppColors.textTertiary,
                              fontSize: 14,
                            ),
                          ),
                        ],
                      )
                    : Wrap(
                        spacing: AppSpacing.sm,
                        runSpacing: AppSpacing.sm,
                        children: [
                          for (final player in picked)
                            Chip(
                              avatar: RoleAvatar(
                                roleId: player.roleId,
                                size: 24,
                                dead: player.dead,
                              ),
                              label: Text(
                                player.seatId != null
                                    ? '${player.seatId}号 ${player.name}'
                                    : player.name,
                              ),
                            ),
                        ],
                      ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// 选魔典：13 张立绘里正好选 11 名。
  Widget _codexField(ActionField field) {
    final selected = List<String>.from(values[field.name] as List? ?? const []);
    final min = field.raw['min'] is int ? field.raw['min'] as int : 11;
    final complete = selected.length == min;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  field.label,
                  style: const TextStyle(
                    fontSize: 13,
                    color: AppColors.textSecondary,
                  ),
                ),
              ),
              Tag(
                '${selected.length} / $min',
                color: complete ? AppColors.success : AppColors.accent,
                background: complete
                    ? AppColors.successSoft
                    : AppColors.accentSoft,
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Material(
            color: AppColors.surfaceMuted,
            borderRadius: BorderRadius.circular(AppRadius.field),
            child: InkWell(
              borderRadius: BorderRadius.circular(AppRadius.field),
              onTap: () async {
                final result = await showCodexPicker(
                  context,
                  initial: selected,
                  requiredCount: min,
                );
                if (result == null) {
                  return;
                }
                setState(() {
                  values[field.name] = result;
                  _saveDraft();
                });
              },
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.all(AppSpacing.md),
                child: selected.isEmpty
                    ? const Text(
                        '点击选择魔典角色',
                        style: TextStyle(color: AppColors.textTertiary),
                      )
                    : Wrap(
                        spacing: AppSpacing.sm,
                        runSpacing: AppSpacing.sm,
                        children: [
                          for (final id in selected)
                            Chip(
                              avatar: RoleAvatar(roleId: id, size: 24),
                              label: Text(roleVisual(id)?.name ?? id),
                            ),
                        ],
                      ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _selectField(ActionField field) {
    final selected = values[field.name]?.toString();
    final label = field.options
        .where((option) => option['value'].toString() == selected)
        .map((option) => option['label'].toString())
        .join();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            field.label,
            style: const TextStyle(
              fontSize: 13,
              color: AppColors.textSecondary,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Material(
            color: AppColors.surfaceMuted,
            borderRadius: BorderRadius.circular(AppRadius.field),
            child: InkWell(
              borderRadius: BorderRadius.circular(AppRadius.field),
              onTap: () async {
                final picked = await _showOptionSheet(
                  context,
                  title: field.label,
                  options: field.options,
                  selected: selected == null ? const [] : [selected],
                  multi: false,
                );
                if (picked == null || picked.isEmpty) {
                  return;
                }
                setState(() {
                  values[field.name] = picked.first;
                  _saveDraft();
                });
              },
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.all(AppSpacing.md),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        label.isEmpty ? '点击选择' : label,
                        style: TextStyle(
                          fontSize: 14,
                          color: label.isEmpty
                              ? AppColors.textTertiary
                              : AppColors.text,
                        ),
                      ),
                    ),
                    const Icon(
                      Icons.expand_more,
                      size: 18,
                      color: AppColors.textTertiary,
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _multiField(ActionField field) {
    final selected = List<String>.from(values[field.name] as List? ?? const []);
    final labels = field.options
        .where((option) => selected.contains(option['value'].toString()))
        .map((option) => option['label'].toString())
        .toList();
    final max = field.raw['max'];
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: FormField<List<String>>(
        initialValue: selected,
        validator: (_) {
          final min = field.raw['min'] is int
              ? field.raw['min'] as int
              : (field.required ? 1 : 0);
          if (selected.length < min) {
            return '至少选择 $min 项';
          }
          if (max is int && selected.length > max) {
            return '最多选择 $max 项';
          }
          return null;
        },
        builder: (state) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    field.label,
                    style: const TextStyle(
                      fontSize: 13,
                      color: AppColors.textSecondary,
                    ),
                  ),
                ),
                if (max is int)
                  Tag(
                    '${selected.length} / $max',
                    color: AppColors.textSecondary,
                    background: AppColors.surfaceMuted,
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            Material(
              color: AppColors.surfaceMuted,
              borderRadius: BorderRadius.circular(AppRadius.field),
              child: InkWell(
                borderRadius: BorderRadius.circular(AppRadius.field),
                onTap: () async {
                  final picked = await _showOptionSheet(
                    context,
                    title: field.label,
                    options: field.options,
                    selected: selected,
                    multi: true,
                    max: max is int ? max : null,
                  );
                  if (picked == null) {
                    return;
                  }
                  setState(() {
                    values[field.name] = picked;
                    state.didChange(picked);
                    _saveDraft();
                  });
                },
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(AppSpacing.md),
                  child: labels.isEmpty
                      ? const Text(
                          '点击选择',
                          style: TextStyle(color: AppColors.textTertiary),
                        )
                      : Wrap(
                          spacing: AppSpacing.sm,
                          runSpacing: AppSpacing.sm,
                          children: [
                            for (final text in labels) Chip(label: Text(text)),
                          ],
                        ),
                ),
              ),
            ),
            if (state.errorText != null)
              Padding(
                padding: const EdgeInsets.only(top: AppSpacing.xs),
                child: Text(
                  state.errorText!,
                  style: const TextStyle(
                    color: AppColors.danger,
                    fontSize: 12,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _orderPreview() {
    final top = values['top']?.toString();
    final cards = widget.store.view?.self['cards'];
    if (top == null || cards is! List) {
      return const SizedBox.shrink();
    }
    String? other;
    for (final raw in cards) {
      if (raw is Map && raw['id']?.toString() != top) {
        other = raw['id']?.toString();
      }
    }
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.sm),
      child: Container(
        padding: const EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: AppColors.accentSoft,
          borderRadius: BorderRadius.circular(AppRadius.field),
        ),
        child: Row(
          children: [
            RoleAvatar(roleId: top, size: 34),
            const SizedBox(width: AppSpacing.sm),
            const Text(
              '上层',
              style: TextStyle(fontSize: 12, color: AppColors.textSecondary),
            ),
            const SizedBox(width: AppSpacing.xs),
            Expanded(
              child: Text(
                roleVisual(top)?.name ?? top,
                style: const TextStyle(
                  fontWeight: FontWeight.w600,
                  color: AppColors.text,
                ),
              ),
            ),
            if (other != null) ...[
              RoleAvatar(roleId: other, size: 30),
              const SizedBox(width: AppSpacing.xs),
              Text(
                '下层 ${roleVisual(other)?.name ?? other}',
                style: const TextStyle(
                  fontSize: 12,
                  color: AppColors.textSecondary,
                ),
              ),
            ],
          ],
        ),
      ),
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
    if (formKey.currentState?.validate() != true) {
      return;
    }
    for (final field in widget.action.fields.where(
      (item) => item.type == 'drawing',
    )) {
      final pad = drawingKeys[field.name]!.currentState;
      if (pad?.hasDrawing == true) {
        values[field.name] = await pad!.toDataUri();
      }
    }
    for (final field in widget.action.fields) {
      final value = values[field.name];
      final empty =
          value == null ||
          (value is String && value.trim().isEmpty) ||
          (value is List && value.isEmpty);
      if (field.required && empty) {
        setState(() => error = '请完成「${field.label}」后再提交');
        return;
      }
    }
    await widget.store.saveDraft(widget.action, values, asSeat: widget.asSeat);
    if (!mounted) {
      return;
    }
    final danger = widget.action.raw['danger'] == true;
    final confirmed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        icon: Icon(
          danger ? Icons.warning_amber_rounded : Icons.fact_check_outlined,
          color: danger ? AppColors.danger : AppColors.accent,
        ),
        title: Text('确认${widget.action.label}'),
        content: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                if (widget.action.description.isNotEmpty)
                  Text(widget.action.description),
                const SizedBox(height: AppSpacing.md),
                for (final field in widget.action.fields)
                  Padding(
                    padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(
                          width: 96,
                          child: Text(
                            field.label,
                            style: const TextStyle(
                              fontSize: 13,
                              color: AppColors.textTertiary,
                            ),
                          ),
                        ),
                        Expanded(
                          child: Text(
                            _displayValue(field, values[field.name]),
                            style: const TextStyle(
                              fontSize: 14,
                              color: AppColors.text,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                if (widget.action.fields.isEmpty)
                  const Text('此行动没有参数，仍需确认后才会提交。'),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('返回检查'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: danger
                ? FilledButton.styleFrom(backgroundColor: AppColors.danger)
                : null,
            child: const Text('确认提交'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) {
      return;
    }
    if (Platform.isAndroid) {
      await HapticFeedback.lightImpact();
    }
    setState(() => submitting = true);
    try {
      await widget.store.execute(widget.action, values, asSeat: widget.asSeat);
      if (mounted) {
        Navigator.pop(context);
      }
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
    if (field.type == 'drawing') {
      return value == null ? '未绘制' : '已绘制';
    }
    if (field.type == 'checkbox') {
      return value == true ? '是' : '否';
    }
    if (value is List) {
      return value.map((item) => _optionLabel(field, item.toString())).join('、');
    }
    if (value == null) {
      return '（空）';
    }
    return _optionLabel(field, value.toString());
  }

  String _optionLabel(ActionField field, String value) {
    for (final option in field.options) {
      if (option['value'].toString() == value) {
        return option['label'].toString();
      }
    }
    final role = roleVisual(value);
    return role?.name ?? value;
  }
}

/// 自绘的单项/多项选择面板。
Future<List<String>?> _showOptionSheet(
  BuildContext context, {
  required String title,
  required List<Map<String, dynamic>> options,
  required List<String> selected,
  required bool multi,
  int? max,
}) => showModalBottomSheet<List<String>>(
  context: context,
  isScrollControlled: true,
  useSafeArea: true,
  builder: (context) => _OptionSheet(
    title: title,
    options: options,
    initial: selected,
    multi: multi,
    max: max,
  ),
);

class _OptionSheet extends StatefulWidget {
  const _OptionSheet({
    required this.title,
    required this.options,
    required this.initial,
    required this.multi,
    this.max,
  });

  final String title;
  final List<Map<String, dynamic>> options;
  final List<String> initial;
  final bool multi;
  final int? max;

  @override
  State<_OptionSheet> createState() => _OptionSheetState();
}

class _OptionSheetState extends State<_OptionSheet> {
  late List<String> chosen = [...widget.initial];

  @override
  Widget build(BuildContext context) {
    final max = widget.max;
    return SizedBox(
      height: MediaQuery.sizeOf(context).height * .7,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.xl,
              0,
              AppSpacing.xl,
              AppSpacing.md,
            ),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    widget.title,
                    style: const TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.w600,
                      color: AppColors.text,
                    ),
                  ),
                ),
                if (max != null)
                  Tag(
                    '${chosen.length} / $max',
                    color: chosen.length > max
                        ? AppColors.danger
                        : AppColors.accent,
                    background: chosen.length > max
                        ? AppColors.dangerSoft
                        : AppColors.accentSoft,
                  ),
              ],
            ),
          ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.lg,
                0,
                AppSpacing.lg,
                AppSpacing.lg,
              ),
              children: [
                for (final option in widget.options)
                  Padding(
                    padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                    child: _optionRow(option, max),
                  ),
              ],
            ),
          ),
          if (widget.multi)
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.lg,
                0,
                AppSpacing.lg,
                AppSpacing.lg,
              ),
              child: SafeArea(
                top: false,
                child: FilledButton(
                  onPressed: () => Navigator.pop(context, chosen),
                  child: Text(
                    chosen.isEmpty ? '清空选择' : '确定（${chosen.length}）',
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _optionRow(Map<String, dynamic> option, int? max) {
    final value = option['value'].toString();
    final label = option['label'].toString();
    final picked = chosen.contains(value);
    final blocked = !picked && max != null && chosen.length >= max;
    final role = roleVisual(value);
    return Opacity(
      opacity: blocked ? .45 : 1,
      child: Material(
        color: picked ? AppColors.accentSoft : AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.field),
        child: InkWell(
          borderRadius: BorderRadius.circular(AppRadius.field),
          onTap: blocked
              ? null
              : () {
                  setState(() {
                    if (widget.multi) {
                      if (picked) {
                        chosen.remove(value);
                      } else {
                        chosen.add(value);
                      }
                    } else {
                      chosen = [value];
                    }
                  });
                  if (!widget.multi) {
                    Navigator.pop(context, chosen);
                  }
                },
          child: Container(
            padding: const EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(AppRadius.field),
              border: Border.all(
                color: picked ? AppColors.accent : AppColors.border,
              ),
            ),
            child: Row(
              children: [
                if (role != null) ...[
                  RoleAvatar(roleId: value, size: 32),
                  const SizedBox(width: AppSpacing.md),
                ],
                Expanded(
                  child: Text(
                    label,
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: picked ? FontWeight.w600 : FontWeight.w500,
                      color: picked ? AppColors.accent : AppColors.text,
                    ),
                  ),
                ),
                Icon(
                  widget.multi
                      ? (picked
                            ? Icons.check_box
                            : Icons.check_box_outline_blank)
                      : (picked
                            ? Icons.radio_button_checked
                            : Icons.radio_button_unchecked),
                  size: 20,
                  color: picked ? AppColors.accent : AppColors.textTertiary,
                ),
              ],
            ),
          ),
        ),
      ),
    );
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
    final boundary =
        boundaryKey.currentContext!.findRenderObject()! as RenderRepaintBoundary;
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
        height: 200,
        decoration: BoxDecoration(
          color: AppColors.surface,
          border: Border.all(color: AppColors.border),
          borderRadius: BorderRadius.circular(AppRadius.field),
        ),
        child: CustomPaint(
          painter: _StrokePainter(points, AppColors.text),
          child: hasDrawing
              ? null
              : const Center(
                  child: Text(
                    '在此手绘',
                    style: TextStyle(
                      color: AppColors.textTertiary,
                      fontSize: 13,
                    ),
                  ),
                ),
        ),
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
      if (from != null && to != null) {
        canvas.drawLine(from, to, paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _StrokePainter oldDelegate) => true;
}
