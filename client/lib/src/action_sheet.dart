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
  Map<String, dynamic>? initial,
}) async {
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => ActionFormSheet(
      store: store,
      action: action,
      asSeat: asSeat,
      initial: initial,
    ),
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
                        style:  TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w600,
                          color: context.palette.text,
                        ),
                      ),
                      Text(
                        '短名：${action.shortLabel} · ${action.group}',
                        style:  TextStyle(
                          fontSize: 12,
                          color: context.palette.textTertiary,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
             SizedBox(height: AppSpacing.lg),
            Text(
              action.description.isEmpty ? '此行动没有补充说明。' : action.description,
              style:  TextStyle(
                fontSize: 14,
                height: 1.6,
                color: context.palette.textSecondary,
              ),
            ),
            if (action.unsupportedReason != null) ...[
               SizedBox(height: AppSpacing.md),
              Text(
                action.unsupportedReason!,
                style:  TextStyle(color: context.palette.danger, fontSize: 13),
              ),
            ],
             SizedBox(height: AppSpacing.lg),
             Text(
              '预览不会提交；点击行动按钮后填写参数，确认一次即会提交。',
              style: TextStyle(fontSize: 12, color: context.palette.textTertiary),
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
    this.initial,
  });

  final GameStore store;
  final ActionDescriptor action;
  final String? asSeat;

  /// 快捷操作预填值：并入草稿键（同一动作按目标隔离草稿），
  /// 且优先于该键下的旧草稿内容，保证快捷入口不会操作错对象。
  final Map<String, dynamic>? initial;

  @override
  State<ActionFormSheet> createState() => _ActionFormSheetState();
}

class _ActionFormSheetState extends State<ActionFormSheet> {
  final formKey = GlobalKey<FormState>();
  final values = <String, dynamic>{};
  final controllers = <String, TextEditingController>{};
  final drawingKeys = <String, GlobalKey<_DrawingPadState>>{};

  /// 手绘笔迹提升到表单层：字段在惰性 ListView 里滚出视口后 State 会被销毁，
  /// 留在 DrawingPad 内部会丢笔迹（提交时报「请完成绘制」或静默丢图）。
  final strokes = <String, List<Offset?>>{};
  String? error;
  bool submitting = false;

  @override
  void initState() {
    super.initState();
    // 草稿按目标隔离（草稿键已含 initial），恢复后由显式预填值覆盖：
    // 快捷入口带出的目标（席位/待办 id）必须优先于旧草稿残留。
    values.addAll(widget.store
        .draftFor(widget.action, asSeat: widget.asSeat, initial: widget.initial));
    values.addAll(widget.initial ?? const <String, dynamic>{});
    for (final field in widget.action.fields) {
      if (!values.containsKey(field.name) && field.raw.containsKey('default')) {
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
        case 'select':
          // 草稿/预填里过期的选项值不允许保留：否则必填校验靠旧值通过，
          // 提交的是当前选项里根本不存在的取值。
          final selected = values[field.name];
          if (selected != null &&
              field.options.every(
                  (option) => option['value'].toString() != selected.toString())) {
            values.remove(field.name);
          }
        case 'multiselect':
          final allowed =
              field.options.map((option) => option['value'].toString()).toSet();
          values[field.name] = List<String>.from(
            values[field.name] as List? ?? const [],
          )..retainWhere(allowed.contains);
        case 'drawing':
          drawingKeys[field.name] = GlobalKey<_DrawingPadState>();
          strokes[field.name] = <Offset?>[];
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
                                color:
                                    danger ? context.palette.danger : context.palette.text,
                              ),
                            ),
                             SizedBox(width: AppSpacing.sm),
                            Tag(
                              action.group,
                              color: context.palette.textSecondary,
                              background: context.palette.surfaceMuted,
                            ),
                          ],
                        ),
                         SizedBox(height: 2),
                        Text(
                          action.description.isEmpty
                              ? action.label
                              : action.description,
                          style:  TextStyle(
                            fontSize: 13,
                            height: 1.5,
                            color: context.palette.textSecondary,
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
                padding:  EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                child: Container(
                  width: double.infinity,
                  padding:  EdgeInsets.all(AppSpacing.md),
                  decoration: BoxDecoration(
                    color: context.palette.dangerSoft,
                    borderRadius: BorderRadius.circular(AppRadius.field),
                  ),
                  child: Row(
                    children: [
                       Icon(
                        Icons.block,
                        size: 18,
                        color: context.palette.danger,
                      ),
                       SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: Text(
                          unsupported,
                          style:  TextStyle(
                            fontSize: 13,
                            color: context.palette.danger,
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
                        padding:  EdgeInsets.only(top: AppSpacing.md),
                        child: Text(
                          error!,
                          style:  TextStyle(
                            color: context.palette.danger,
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
                    onPressed: unsupported != null ||
                            submitting ||
                            widget.store.writeBusy
                        ? null
                        : submit,
                    style: danger
                        ? FilledButton.styleFrom(
                            backgroundColor: context.palette.danger,
                          )
                        : null,
                    icon: Icon(
                      danger
                          ? Icons.warning_amber_rounded
                          : Icons.check_circle_outline,
                      size: 18,
                    ),
                    label:  Text('确认提交'),
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
        padding:  EdgeInsets.symmetric(vertical: AppSpacing.sm),
        child: Text(reason, style:  TextStyle(color: context.palette.danger)),
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
          padding:  EdgeInsets.symmetric(vertical: AppSpacing.xs),
          child: Material(
            color: checked ? context.palette.accentSoft : context.palette.surface,
            borderRadius: BorderRadius.circular(AppRadius.field),
            child: InkWell(
              borderRadius: BorderRadius.circular(AppRadius.field),
              onTap: () => setState(() {
                values[field.name] = !checked;
                _saveDraft();
              }),
              child: Container(
                padding:  EdgeInsets.all(AppSpacing.md),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(AppRadius.field),
                  border: Border.all(
                    color: checked ? context.palette.accent : context.palette.border,
                  ),
                ),
                child: Row(
                  children: [
                    Icon(
                      checked ? Icons.check_box : Icons.check_box_outline_blank,
                      color:
                          checked ? context.palette.accent : context.palette.textTertiary,
                    ),
                     SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: Text(
                        field.label,
                        style:  TextStyle(
                          fontSize: 14,
                          color: context.palette.text,
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
                  strokes[field.name]?.any((point) => point != null) == true;
              return field.required && !retained && !drawn ? '请完成绘制' : null;
            },
            builder: (state) => Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                     Icon(
                      Icons.brush_outlined,
                      size: 18,
                      color: context.palette.textSecondary,
                    ),
                     SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Text(
                        field.label,
                        style:  TextStyle(
                          fontSize: 14,
                          color: context.palette.text,
                        ),
                      ),
                    ),
                    if (values[field.name] != null)
                       Tag(
                        '已保留上次草稿',
                        color: context.palette.textSecondary,
                        background: context.palette.surfaceMuted,
                      ),
                  ],
                ),
                const SizedBox(height: AppSpacing.sm),
                DrawingPad(
                  key: drawingKeys[field.name],
                  points: strokes[field.name]!,
                ),
                Row(
                  children: [
                    TextButton.icon(
                      onPressed: () {
                        setState(() => strokes[field.name]!.clear());
                        values.remove(field.name);
                        state.didChange(null);
                        _saveDraft();
                      },
                      icon:  Icon(Icons.delete_outline, size: 16),
                      label:  Text('清除'),
                    ),
                  ],
                ),
                if (state.errorText != null)
                  Text(
                    state.errorText!,
                    style:  TextStyle(
                      color: context.palette.danger,
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
    final picked =
        players.where((player) => selected.contains(player.id)).toList();
    return Padding(
      padding:  EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            field.label,
            style:  TextStyle(
              fontSize: 13,
              color: context.palette.textSecondary,
            ),
          ),
           SizedBox(height: AppSpacing.sm),
          Material(
            color: context.palette.surfaceMuted,
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
                padding:  EdgeInsets.all(AppSpacing.md),
                child: field.options.isEmpty
                    ?  Text(
                        '当前没有可选参与者',
                        style: TextStyle(color: context.palette.textTertiary),
                      )
                    : picked.isEmpty
                        ? Row(
                            children: [
                               Icon(
                                Icons.person_add_alt,
                                size: 18,
                                color: context.palette.textTertiary,
                              ),
                               SizedBox(width: AppSpacing.sm),
                              Text(
                                multi ? '点击选择成员' : '点击选择参与者',
                                style:  TextStyle(
                                  color: context.palette.textTertiary,
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
      padding:  EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  field.label,
                  style:  TextStyle(
                    fontSize: 13,
                    color: context.palette.textSecondary,
                  ),
                ),
              ),
              Tag(
                '${selected.length} / $min',
                color: complete ? context.palette.success : context.palette.accent,
                background:
                    complete ? context.palette.successSoft : context.palette.accentSoft,
              ),
            ],
          ),
           SizedBox(height: AppSpacing.sm),
          Material(
            color: context.palette.surfaceMuted,
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
                padding:  EdgeInsets.all(AppSpacing.md),
                child: selected.isEmpty
                    ?  Text(
                        '点击选择魔典角色',
                        style: TextStyle(color: context.palette.textTertiary),
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
      padding:  EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            field.label,
            style:  TextStyle(
              fontSize: 13,
              color: context.palette.textSecondary,
            ),
          ),
           SizedBox(height: AppSpacing.sm),
          Material(
            color: context.palette.surfaceMuted,
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
                padding:  EdgeInsets.all(AppSpacing.md),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        label.isEmpty ? '点击选择' : label,
                        style: TextStyle(
                          fontSize: 14,
                          color: label.isEmpty
                              ? context.palette.textTertiary
                              : context.palette.text,
                        ),
                      ),
                    ),
                     Icon(
                      Icons.expand_more,
                      size: 18,
                      color: context.palette.textTertiary,
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
                    style:  TextStyle(
                      fontSize: 13,
                      color: context.palette.textSecondary,
                    ),
                  ),
                ),
                if (max is int)
                  Tag(
                    '${selected.length} / $max',
                    color: context.palette.textSecondary,
                    background: context.palette.surfaceMuted,
                  ),
              ],
            ),
             SizedBox(height: AppSpacing.sm),
            Material(
              color: context.palette.surfaceMuted,
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
                  padding:  EdgeInsets.all(AppSpacing.md),
                  child: labels.isEmpty
                      ?  Text(
                          '点击选择',
                          style: TextStyle(color: context.palette.textTertiary),
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
                padding:  EdgeInsets.only(top: AppSpacing.xs),
                child: Text(
                  state.errorText!,
                  style:  TextStyle(
                    color: context.palette.danger,
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
      return  SizedBox.shrink();
    }
    String? other;
    for (final raw in cards) {
      if (raw is Map && raw['id']?.toString() != top) {
        other = raw['id']?.toString();
      }
    }
    return Padding(
      padding:  EdgeInsets.only(top: AppSpacing.sm),
      child: Container(
        padding:  EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: context.palette.accentSoft,
          borderRadius: BorderRadius.circular(AppRadius.field),
        ),
        child: Row(
          children: [
            RoleAvatar(roleId: top, size: 34),
             SizedBox(width: AppSpacing.sm),
             Text(
              '上层',
              style: TextStyle(fontSize: 12, color: context.palette.textSecondary),
            ),
             SizedBox(width: AppSpacing.xs),
            Expanded(
              child: Text(
                roleVisual(top)?.name ?? top,
                style:  TextStyle(
                  fontWeight: FontWeight.w600,
                  color: context.palette.text,
                ),
              ),
            ),
            if (other != null) ...[
              RoleAvatar(roleId: other, size: 30),
               SizedBox(width: AppSpacing.xs),
              Text(
                '下层 ${roleVisual(other)?.name ?? other}',
                style:  TextStyle(
                  fontSize: 12,
                  color: context.palette.textSecondary,
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
    widget.store.saveDraft(widget.action, values,
        asSeat: widget.asSeat, initial: widget.initial);
  }

  /// 单次确认：校验通过后直接提交，不再弹二次确认框。
  /// 危险动作仍以红色按钮与警告图标双重标记；写命令带 expected_version，
  /// 服务端版本变化会返回 409，由错误提示要求重新确认，不会静默写入。
  Future<void> submit() async {
    setState(() => error = null);
    if (formKey.currentState?.validate() != true) {
      return;
    }
    for (final field in widget.action.fields.where(
      (item) => item.type == 'drawing',
    )) {
      final hasDrawing =
          strokes[field.name]?.any((point) => point != null) == true;
      if (hasDrawing) {
        // 画板滚出视口后没有可截图的渲染对象；笔迹已在 strokes 里保留，
        // 让用户滚回去再提交，绝不静默丢图。
        final pad = drawingKeys[field.name]?.currentState;
        if (pad == null) {
          setState(() => error = '请回到「${field.label}」处再提交，已画的笔迹不会丢失');
          return;
        }
        values[field.name] = await pad.toDataUri();
      }
    }
    for (final field in widget.action.fields) {
      final value = values[field.name];
      final empty = value == null ||
          (value is String && value.trim().isEmpty) ||
          (value is List && value.isEmpty);
      if (field.required && empty) {
        setState(() => error = '请完成「${field.label}」后再提交');
        return;
      }
    }
    if (!mounted) {
      return;
    }
    await widget.store.saveDraft(widget.action, values, asSeat: widget.asSeat);
    if (Platform.isAndroid) {
      await HapticFeedback.lightImpact();
    }
    setState(() => submitting = true);
    try {
      await widget.store.execute(widget.action, values,
          asSeat: widget.asSeat, initial: widget.initial);
      if (mounted) {
        Navigator.pop(context);
      }
    } on ApiException catch (failure) {
      if (mounted) {
        setState(() {
          error = failure.isConflict
              ? '${failure.message}。草稿已保留，请检查刷新后的状态并重新确认。'
              : failure.message;
          submitting = false;
        });
      }
    } catch (failure) {
      // store 已把已知异常归一成 error；这里是最后防线：
      // 任何漏网异常都不能把表单永远卡在“提交中”。
      if (mounted) {
        setState(() {
          error = '提交失败：$failure';
          submitting = false;
        });
      }
    }
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
}) =>
    showModalBottomSheet<List<String>>(
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
                    style:  TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.w600,
                      color: context.palette.text,
                    ),
                  ),
                ),
                if (max != null)
                  Tag(
                    '${chosen.length} / $max',
                    color: chosen.length > max
                        ? context.palette.danger
                        : context.palette.accent,
                    background: chosen.length > max
                        ? context.palette.dangerSoft
                        : context.palette.accentSoft,
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
        color: picked ? context.palette.accentSoft : context.palette.surface,
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
            padding:  EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(AppRadius.field),
              border: Border.all(
                color: picked ? context.palette.accent : context.palette.border,
              ),
            ),
            child: Row(
              children: [
                if (role != null) ...[
                  RoleAvatar(roleId: value, size: 32),
                   SizedBox(width: AppSpacing.md),
                ],
                Expanded(
                  child: Text(
                    label,
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: picked ? FontWeight.w600 : FontWeight.w500,
                      color: picked ? context.palette.accent : context.palette.text,
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
                  color: picked ? context.palette.accent : context.palette.textTertiary,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 手绘板：笔迹由调用方持有（表单层 State），滚出惰性列表重建后不丢。
class DrawingPad extends StatefulWidget {
  const DrawingPad({super.key, required this.points});

  final List<Offset?> points;

  @override
  State<DrawingPad> createState() => _DrawingPadState();
}

class _DrawingPadState extends State<DrawingPad> {
  final boundaryKey = GlobalKey();

  bool get hasDrawing => widget.points.any((point) => point != null);

  Future<String> toDataUri() async {
    final boundary = boundaryKey.currentContext!.findRenderObject()!
        as RenderRepaintBoundary;
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
          onPanEnd: (_) => setState(() => widget.points.add(null)),
          child: Container(
            height: 200,
            decoration: BoxDecoration(
              color: context.palette.surface,
              border: Border.all(color: context.palette.border),
              borderRadius: BorderRadius.circular(AppRadius.field),
            ),
            child: CustomPaint(
              painter: _StrokePainter(widget.points, context.palette.text),
              child: hasDrawing
                  ? null
                  :  Center(
                      child: Text(
                        '在此手绘',
                        style: TextStyle(
                          color: context.palette.textTertiary,
                          fontSize: 13,
                        ),
                      ),
                    ),
            ),
          ),
        ),
      );

  void _add(Offset point) => setState(() => widget.points.add(point));
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
