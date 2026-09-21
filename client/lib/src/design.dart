import 'package:flutter/material.dart';

/// 语义色板：浅色与深色两套，界面通过 `context.palette` 取色。
/// 浅色值与旧 AppColors 逐字一致（golden 图依赖浅色渲染结果）。
@immutable
class AppPalette {
  const AppPalette({
    required this.background,
    required this.surface,
    required this.surfaceMuted,
    required this.surfaceStrong,
    required this.border,
    required this.borderStrong,
    required this.text,
    required this.textSecondary,
    required this.textTertiary,
    required this.onAccent,
    required this.accent,
    required this.accentSoft,
    required this.host,
    required this.hostSoft,
    required this.success,
    required this.successSoft,
    required this.warning,
    required this.warningSoft,
    required this.danger,
    required this.dangerSoft,
    required this.info,
    required this.dead,
  });

  final Color background;
  final Color surface;
  final Color surfaceMuted;
  final Color surfaceStrong;
  final Color border;
  final Color borderStrong;
  final Color text;
  final Color textSecondary;
  final Color textTertiary;
  final Color onAccent;
  final Color accent;
  final Color accentSoft;
  final Color host;
  final Color hostSoft;
  final Color success;
  final Color successSoft;
  final Color warning;
  final Color warningSoft;
  final Color danger;
  final Color dangerSoft;
  final Color info;
  final Color dead;

  static const light = AppPalette(
    background: Color(0xFFF7F8FA),
    surface: Color(0xFFFFFFFF),
    surfaceMuted: Color(0xFFF2F3F7),
    surfaceStrong: Color(0xFFE9EAF0),
    border: Color(0xFFE7E8EF),
    borderStrong: Color(0xFFD8DAE3),
    text: Color(0xFF17181C),
    textSecondary: Color(0xFF585B66),
    textTertiary: Color(0xFF8E919C),
    onAccent: Color(0xFFFFFFFF),
    accent: Color(0xFF6C5CE7),
    accentSoft: Color(0xFFEDEBFD),
    host: Color(0xFFC08A2E),
    hostSoft: Color(0xFFFBF3E3),
    success: Color(0xFF2E9E6B),
    successSoft: Color(0xFFE8F6EF),
    warning: Color(0xFFD9822B),
    warningSoft: Color(0xFFFDF2E4),
    danger: Color(0xFFD64550),
    dangerSoft: Color(0xFFFCEDEE),
    info: Color(0xFF3B7DD8),
    dead: Color(0xFFB4B7C0),
  );

  static const dark = AppPalette(
    background: Color(0xFF14151A),
    surface: Color(0xFF1D1E24),
    surfaceMuted: Color(0xFF26272E),
    surfaceStrong: Color(0xFF32333B),
    border: Color(0xFF33353D),
    borderStrong: Color(0xFF454751),
    text: Color(0xFFECEDF2),
    textSecondary: Color(0xFFB6B9C4),
    textTertiary: Color(0xFF8B8E99),
    onAccent: Color(0xFF14151A),
    accent: Color(0xFF9A8CFF),
    accentSoft: Color(0xFF2A2740),
    host: Color(0xFFE0B15C),
    hostSoft: Color(0xFF3A2F1B),
    success: Color(0xFF4FC08D),
    successSoft: Color(0xFF1C3A2C),
    warning: Color(0xFFE7A24D),
    warningSoft: Color(0xFF3A2C1A),
    danger: Color(0xFFEF6F79),
    dangerSoft: Color(0xFF3A2124),
    info: Color(0xFF6FA6EA),
    dead: Color(0xFF6C707B),
  );

  static AppPalette of(BuildContext context) =>
      Theme.of(context).brightness == Brightness.dark ? dark : light;
}

extension AppPaletteAccess on BuildContext {
  AppPalette get palette => AppPalette.of(this);
}

class AppRadius {
  const AppRadius._();

  static const card = 18.0;
  static const sheet = 28.0;
  static const field = 14.0;
  static const chip = 999.0;
}

/// 宽屏断点：达到后同屏显示多个界面，不再用悬浮底栏一次只露出一页。
/// 采用 Material 3 窗口尺寸类：840（expanded）起两栏，1200（large）起三栏。
/// 平板竖屏与手机仍在 840 以下，保持原来的单页加底栏。
class AppBreakpoints {
  const AppBreakpoints._();

  /// 平板横屏与小窗口桌面：状态与对局同屏，「我的/管理」收进右侧抽屉。
  static const dualPane = 840.0;

  /// 电脑：状态、对局与「我的/管理」三栏同屏。
  static const triplePane = 1200.0;
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

/// 语义色主题：浅色与深色共用同一套结构，界面跟随系统深色开关。
ThemeData buildAppTheme([Brightness brightness = Brightness.light]) {
  final palette = brightness == Brightness.dark ? AppPalette.dark : AppPalette.light;
  final scheme = ColorScheme.fromSeed(
    seedColor: palette.accent,
    brightness: brightness,
  ).copyWith(
    surface: palette.surface,
    onSurface: palette.text,
    primary: palette.accent,
    onPrimary: palette.onAccent,
    error: palette.danger,
  );
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: palette.background,
    fontFamily: kAppFontFamily,
  );
  return base.copyWith(
    appBarTheme: AppBarTheme(
      backgroundColor: palette.background,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        fontFamily: kAppFontFamily,
        fontSize: 20,
        fontWeight: FontWeight.w600,
        color: palette.text,
      ),
      iconTheme: IconThemeData(color: palette.text),
    ),
    cardTheme: CardThemeData(
      color: palette.surface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.card),
        side: BorderSide(color: palette.border),
      ),
    ),
    dividerTheme: DividerThemeData(
      color: palette.border,
      thickness: 1,
      space: 1,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: palette.surfaceMuted,
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
        borderSide: BorderSide(color: palette.accent, width: 1.6),
      ),
      hintStyle: TextStyle(color: palette.textTertiary),
      labelStyle: TextStyle(color: palette.textSecondary),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: palette.accent,
        foregroundColor: palette.onAccent,
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
        foregroundColor: palette.text,
        minimumSize: const Size(0, 48),
        padding: const EdgeInsets.symmetric(horizontal: 20),
        side: BorderSide(color: palette.borderStrong),
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
        foregroundColor: palette.accent,
        textStyle: const TextStyle(
          fontFamily: kAppFontFamily,
          fontSize: 15,
          fontWeight: FontWeight.w500,
        ),
      ),
    ),
    listTileTheme: ListTileThemeData(
      iconColor: palette.textSecondary,
      textColor: palette.text,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: palette.surface,
      surfaceTintColor: Colors.transparent,
      indicatorColor: palette.accentSoft,
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
              ? palette.accent
              : palette.textTertiary,
        ),
      ),
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          size: 24,
          color: states.contains(WidgetState.selected)
              ? palette.accent
              : palette.textTertiary,
        ),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: palette.text,
      contentTextStyle:
          const TextStyle(fontFamily: kAppFontFamily, color: Colors.white),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.field)),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: palette.surface,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.sheet)),
      titleTextStyle: TextStyle(
        fontFamily: kAppFontFamily,
        fontSize: 19,
        fontWeight: FontWeight.w600,
        color: palette.text,
      ),
      contentTextStyle: TextStyle(
        fontFamily: kAppFontFamily,
        fontSize: 15,
        height: 1.6,
        color: palette.textSecondary,
      ),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: palette.surface,
      surfaceTintColor: Colors.transparent,
      showDragHandle: true,
      shape: RoundedRectangleBorder(
        borderRadius:
            BorderRadius.vertical(top: Radius.circular(AppRadius.sheet)),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: palette.surfaceMuted,
      selectedColor: palette.accentSoft,
      side: BorderSide.none,
      labelStyle: TextStyle(
        fontFamily: kAppFontFamily,
        fontSize: 13,
        fontWeight: FontWeight.w500,
        color: palette.textSecondary,
      ),
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.chip)),
    ),
    progressIndicatorTheme:
        ProgressIndicatorThemeData(color: palette.accent),
    textTheme: base.textTheme.apply(
      fontFamily: kAppFontFamily,
      bodyColor: palette.text,
      displayColor: palette.text,
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
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w600,
                      color: context.palette.text,
                    ),
                  ),
                  if (subtitle != null) ...[
                     SizedBox(height: AppSpacing.xs),
                    Text(
                      subtitle!,
                      style: TextStyle(
                          fontSize: 13, color: context.palette.textTertiary),
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
   Tag(this.text, {super.key, this.color, this.background, this.icon});

  final String text;
  final Color? color;
  final Color? background;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final color = this.color ?? context.palette.accent;
    final background = this.background ?? context.palette.accentSoft;
    return Container(
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
          padding:  EdgeInsets.all(AppSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 64,
                height: 64,
                decoration: BoxDecoration(
                    color: context.palette.surfaceMuted, shape: BoxShape.circle),
                child: Icon(icon,
                    size: 30, color: context.palette.textTertiary),
              ),
               SizedBox(height: AppSpacing.lg),
              Text(
                title,
                textAlign: TextAlign.center,
                style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                    color: context.palette.text),
              ),
              if (detail != null) ...[
                 SizedBox(height: AppSpacing.sm),
                Text(
                  detail!,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                      fontSize: 13,
                      height: 1.6,
                      color: context.palette.textTertiary),
                ),
              ],
            ],
          ),
        ),
      );
}
