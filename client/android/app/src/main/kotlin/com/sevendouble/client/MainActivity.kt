package com.sevendouble.client

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.core.content.FileProvider
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: android.os.Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "keepalive")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "ignoringBatteryOptimizations" -> {
                        val manager = getSystemService(POWER_SERVICE) as PowerManager
                        result.success(manager.isIgnoringBatteryOptimizations(packageName))
                    }
                    "requestIgnoreBatteryOptimizations" -> {
                        try {
                            startActivity(
                                Intent(
                                    Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                                    Uri.parse("package:$packageName"),
                                )
                            )
                            result.success(true)
                        } catch (failure: Exception) {
                            // 少数 ROM 不提供该入口，退到电池优化列表页。
                            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
                            result.success(false)
                        }
                    }
                    "notifyInvite" -> {
                        val title = call.argument<String>("title") ?: "魔法裁判"
                        val body = call.argument<String>("body") ?: ""
                        notifyInvite(title, body)
                        result.success(true)
                    }
                    else -> result.notImplemented()
                }
            }
        // 应用内更新：打开引导网页 + 把下载好的 APK 交给系统安装器。
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "client_update")
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "openUrl" -> {
                        val url = call.argument<String>("url") ?: ""
                        result.success(openUrl(url))
                    }
                    "canInstallPackages" -> result.success(canInstallPackages())
                    "requestInstallPermission" -> {
                        requestInstallPermission()
                        result.success(true)
                    }
                    "installApk" -> {
                        val path = call.argument<String>("path") ?: ""
                        result.success(installApk(path))
                    }
                    else -> result.notImplemented()
                }
            }
    }

    /// 用系统默认浏览器打开网页；没有可用浏览器时返回 false（界面退回复制链接）。
    private fun openUrl(url: String): Boolean {
        if (url.isEmpty()) return false
        return try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            true
        } catch (failure: Exception) {
            false
        }
    }

    /// Android 8.0 起安装未知来源应用是「按应用授权」，而不是全局开关。
    private fun canInstallPackages(): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            packageManager.canRequestPackageInstalls()
        } else {
            true
        }

    private fun requestInstallPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        try {
            startActivity(
                Intent(
                    Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:$packageName"),
                )
            )
        } catch (failure: Exception) {
            // 少数 ROM 没有这个入口：下次点「更新」会直接尝试拉起安装器。
        }
    }

    /// 拉起系统安装器。返回 "launched" / "permission-required" / "failed"。
    /// 安装包在应用缓存目录里，必须经 FileProvider 转成 content:// 并授权读取，
    /// 否则安装器（另一个进程）读不到文件。
    private fun installApk(path: String): String {
        val file = File(path)
        if (!file.exists()) return "failed"
        if (!canInstallPackages()) return "permission-required"
        return try {
            val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", file)
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, "application/vnd.android.package-archive")
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            startActivity(intent)
            "launched"
        } catch (failure: Exception) {
            "failed"
        }
    }

    /// 对局邀请的系统通知：应用切到后台时界面横幅看不到，靠通知栏补一次提醒。
    private fun notifyInvite(title: String, body: String) {
        val manager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        // IMPORTANCE_HIGH 才会在锁屏与后台弹出横幅；频道已存在时系统沿用旧设置。
        manager.createNotificationChannel(
            NotificationChannel(
                INVITE_CHANNEL_ID,
                "对局邀请",
                NotificationManager.IMPORTANCE_HIGH,
            )
        )
        val launch = PendingIntent.getActivity(
            this,
            0,
            packageManager.getLaunchIntentForPackage(packageName),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, INVITE_CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        val notification = builder
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(body)
            .setContentIntent(launch)
            // 每人固定 ID：多条邀请只留最新一条，答复后由系统手动清除。
            .setAutoCancel(true)
            .build()
        try {
            manager.notify(INVITE_NOTIFICATION_ID, notification)
        } catch (failure: SecurityException) {
            // 用户没给通知权限：静默放弃，邀请在大厅里依然可见。
        }
    }

    override fun onStart() {
        super.onStart()
        KeepAliveService.start(this)
    }

    companion object {
        private const val INVITE_CHANNEL_ID = "invites"
        private const val INVITE_NOTIFICATION_ID = 2
    }
}
