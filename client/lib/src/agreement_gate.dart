import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

import 'announcement_pages.dart' show markdownStyleSheet;
import 'app_icons.dart';
import 'design.dart';
import 'store.dart';

/// 首次连接服务器时的用户协议门。
///
/// 正文是服务端下发的 Markdown（`GET /api/agreement`），用户只有两个选择：
/// 「同意并继续」把「服务地址 + 协议内容哈希」记在本机；
/// 「取消连接」清掉这个服务地址、回到地址输入页（不写同意记录）。
/// 协议内容改过（哈希变了）会重新问一次。
class AgreementGate extends StatelessWidget {
  const AgreementGate({super.key, required this.store});

  final GameStore store;

  @override
  Widget build(BuildContext context) {
    if (store.agreementLoading) {
      return const Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              SizedBox(
                width: 22,
                height: 22,
                child: CircularProgressIndicator(strokeWidth: 2.4),
              ),
              SizedBox(height: AppSpacing.lg),
              Text('正在获取用户协议…'),
            ],
          ),
        ),
      );
    }
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.lg,
                AppSpacing.lg,
                AppSpacing.lg,
                AppSpacing.sm,
              ),
              child: Row(
                children: [
                  const AppLogo(size: 40, rounded: true),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '用户协议',
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w600,
                            color: context.palette.text,
                          ),
                        ),
                        Text(
                          '连接服务器前请先阅读并确认',
                          style: TextStyle(
                            fontSize: 12,
                            color: context.palette.textTertiary,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            Expanded(
              child: Card(
                margin: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(AppSpacing.lg),
                  child: MarkdownBody(
                    data: store.agreement.text,
                    selectable: true,
                    styleSheet: markdownStyleSheet(context),
                  ),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  FilledButton.icon(
                    onPressed: () => store.acceptAgreement(),
                    icon: const Icon(Icons.check_rounded, size: 18),
                    label: const Text('同意并继续'),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  OutlinedButton(
                    onPressed: () => store.clearEndpoint(),
                    child: const Text('取消连接'),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
