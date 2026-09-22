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
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

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
