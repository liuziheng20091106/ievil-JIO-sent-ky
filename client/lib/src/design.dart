import 'package:flutter/material.dart';

/// 浅色极简设计令牌：白底、大标题分区、充足留白、圆角卡片。
class AppColors {
  const AppColors._();

  static const background = Color(0xFFF7F8FA);
  static const surface = Color(0xFFFFFFFF);
  static const surfaceMuted = Color(0xFFF2F3F7);
  static const surfaceStrong = Color(0xFFE9EAF0);
  static const border = Color(0xFFE7E8EF);
  static const borderStrong = Color(0xFFD8DAE3);

  static const text = Color(0xFF17181C);
  static const textSecondary = Color(0xFF585B66);
  static const textTertiary = Color(0xFF8E919C);
  static const onAccent = Color(0xFFFFFFFF);

  /// 行动与强调色；魔女审判题材保留紫色。
  static const accent = Color(0xFF6C5CE7);
  static const accentSoft = Color(0xFFEDEBFD);

  static const host = Color(0xFFC08A2E);
  static const hostSoft = Color(0xFFFBF3E3);

  static const success = Color(0xFF2E9E6B);
  static const successSoft = Color(0xFFE8F6EF);
  static const warning = Color(0xFFD9822B);
  static const warningSoft = Color(0xFFFDF2E4);
  static const danger = Color(0xFFD64550);
  static const dangerSoft = Color(0xFFFCEDEE);
  static const info = Color(0xFF3B7DD8);

  static const dead = Color(0xFFB4B7C0);
}

class AppRadius {
  const AppRadius._();

  static const card = 18.0;
  static const sheet = 28.0;
  static const field = 14.0;
  static const chip = 999.0;
}

class AppSpacing {
  const AppSpacing._();

  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 12.0;
  static const lg = 16.0;
  static const xl = 24.0;
  static const xxl = 32.0;

  /// 悬浮底栏占位，避免内容被遮住。
  static const bottomBar = 104.0;
}

/// 浅色极简主题；不再提供暗色主题，界面统一跟随这一套。
ThemeData buildAppTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: AppColors.accent,
    brightness: Brightness.light,
  ).copyWith(
    surface: AppColors.surface,
    onSurface: AppColors.text,
    primary: AppColors.accent,
    onPrimary: AppColors.onAccent,
    error: AppColors.danger,
  );
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: AppColors.background,
    fontFamily: kAppFontFamily,
  );
  return base.copyWith(
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.background,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        fontFamily: kAppFontFamily,
        fontSize: 20,
        fontWeight: FontWeight.w600,
        color: AppColors.text,
      ),
      iconTheme: IconThemeData(color: AppColors.text),
    ),
    cardTheme: CardThemeData(
      color: AppColors.surface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.card),
        side: const BorderSide(color: AppColors.border),
      ),
    ),
    dividerTheme: const DividerThemeData(
      color: AppColors.border,
      thickness: 1,
      space: 1,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.surfaceMuted,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.field),
        borderSide: BorderSide.none,
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.field),
        borderSide: BorderSide.none,
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.field),
        borderSide: const BorderSide(color: AppColors.accent, width: 1.6),
      ),
      hintStyle: const TextStyle(color: AppColors.textTertiary),
      labelStyle: const TextStyle(color: AppColors.textSecondary),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: AppColors.accent,
        foregroundColor: AppColors.onAccent,
        minimumSize: const Size(0, 48),
        padding: const EdgeInsets.symmetric(horizontal: 20),
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.field)),
        textStyle: const TextStyle(
          fontFamily: kAppFontFamily,
          fontSize: 15,
          fontWeight: FontWeight.w600,
        ),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: AppColors.text,
        minimumSize: const Size(0, 48),
        padding: const EdgeInsets.symmetric(horizontal: 20),
        side: const BorderSide(color: AppColors.borderStrong),
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.field)),
        textStyle: const TextStyle(
          fontFamily: kAppFontFamily,
          fontSize: 15,
          fontWeight: FontWeight.w500,
        ),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: AppColors.accent,
        textStyle: const TextStyle(
          fontFamily: kAppFontFamily,
          fontSize: 15,
          fontWeight: FontWeight.w500,
        ),
      ),
    ),
    listTileTheme: const ListTileThemeData(
      iconColor: AppColors.textSecondary,
      textColor: AppColors.text,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: AppColors.surface,
      surfaceTintColor: Colors.transparent,
      indicatorColor: AppColors.accentSoft,
      elevation: 0,
      height: 64,
      labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => TextStyle(
          fontFamily: kAppFontFamily,
          fontSize: 12,
          fontWeight: states.contains(WidgetState.selected)
              ? FontWeight.w600
              : FontWeight.w500,
          color: states.contains(WidgetState.selected)
              ? AppColors.accent
              : AppColors.textTertiary,
        ),
      ),
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          size: 24,
          color: states.contains(WidgetState.selected)
              ? AppColors.accent
              : AppColors.textTertiary,
        ),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: AppColors.text,
      contentTextStyle:
          const TextStyle(fontFamily: kAppFontFamily, color: Colors.white),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.field)),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: AppColors.surface,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.sheet)),
      titleTextStyle: const TextStyle(
        fontFamily: kAppFontFamily,
        fontSize: 19,
        fontWeight: FontWeight.w600,
        color: AppColors.text,
      ),
      contentTextStyle: const TextStyle(
        fontFamily: kAppFontFamily,
        fontSize: 15,
        height: 1.6,
        color: AppColors.textSecondary,
      ),
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: AppColors.surface,
      surfaceTintColor: Colors.transparent,
      showDragHandle: true,
      shape: RoundedRectangleBorder(
        borderRadius:
            BorderRadius.vertical(top: Radius.circular(AppRadius.sheet)),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: AppColors.surfaceMuted,
      selectedColor: AppColors.accentSoft,
      side: BorderSide.none,
      labelStyle: const TextStyle(
        fontFamily: kAppFontFamily,
        fontSize: 13,
        fontWeight: FontWeight.w500,
        color: AppColors.textSecondary,
      ),
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.chip)),
    ),
    progressIndicatorTheme:
        const ProgressIndicatorThemeData(color: AppColors.accent),
    textTheme: base.textTheme.apply(
      fontFamily: kAppFontFamily,
      bodyColor: AppColors.text,
      displayColor: AppColors.text,
    ),
  );
}

/// 字体家族常量放在这里，避免主题与 main.dart 循环依赖。
const kAppFontFamily = 'HarmonyOS Sans SC';
const kAppTitle = '魔法裁判';

/// 分区大标题。
class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing, this.subtitle});

  final String text;
  final Widget? trailing;
  final String? subtitle;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(
            AppSpacing.xs, AppSpacing.xl, AppSpacing.xs, AppSpacing.md),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    text,
                    style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w600,
                      color: AppColors.text,
                    ),
                  ),
                  if (subtitle != null) ...[
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      subtitle!,
                      style: const TextStyle(
                          fontSize: 13, color: AppColors.textTertiary),
                    ),
                  ],
                ],
              ),
            ),
            if (trailing != null) trailing!,
          ],
        ),
      );
}

/// 小标签。
class Tag extends StatelessWidget {
  const Tag(this.text,
      {super.key,
      this.color = AppColors.accent,
      this.background = AppColors.accentSoft,
      this.icon});

  final String text;
  final Color color;
  final Color background;
  final IconData? icon;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: background,
          borderRadius: BorderRadius.circular(AppRadius.chip),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[
              Icon(icon, size: 13, color: color),
              const SizedBox(width: 4),
            ],
            Text(
              text,
              style: TextStyle(
                  fontSize: 12, fontWeight: FontWeight.w600, color: color),
            ),
          ],
        ),
      );
}

/// 空状态：图标 + 说明，替代空白页。
class EmptyState extends StatelessWidget {
  const EmptyState(
      {super.key, required this.icon, required this.title, this.detail});

  final IconData icon;
  final String title;
  final String? detail;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 64,
                height: 64,
                decoration: const BoxDecoration(
                    color: AppColors.surfaceMuted, shape: BoxShape.circle),
                child: Icon(icon, size: 30, color: AppColors.textTertiary),
              ),
              const SizedBox(height: AppSpacing.lg),
              Text(
                title,
                textAlign: TextAlign.center,
                style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                    color: AppColors.text),
              ),
              if (detail != null) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  detail!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                      fontSize: 13, height: 1.6, color: AppColors.textTertiary),
                ),
              ],
            ],
          ),
        ),
      );
}
