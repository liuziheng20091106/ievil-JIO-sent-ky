#ifndef RUNNER_SINGLE_INSTANCE_H_
#define RUNNER_SINGLE_INSTANCE_H_

#include <windows.h>

#include "win32_window.h"

// Windows 主持人端只允许一个实例：第二次启动不再开新窗口，而是把已在运行的
// 窗口拉到前台后退出。互斥体名带 "Local\\" 前缀，只在当前登录会话内生效，
// 不影响同一台电脑上另一个 Windows 用户；进程结束（含崩溃）时由系统释放。
inline constexpr const wchar_t kSingleInstanceMutexName[] =
    L"Local\\MagicJudge.SevenDouble.WindowsHost";

// 取得本进程的单实例所有权。
// 返回 nullptr 表示本进程是唯一实例，调用方必须持有该句柄直到进程结束。
// 返回 INVALID_HANDLE_VALUE 表示已有实例在运行，调用方应当退出。
inline HANDLE ClaimSingleInstance() {
  ::SetLastError(ERROR_SUCCESS);
  HANDLE mutex = ::CreateMutexW(nullptr, FALSE, kSingleInstanceMutexName);
  if (mutex == nullptr) {
    // 互斥体创建失败时宁可放行：不要因为保护机制本身出错而让客户端打不开。
    return nullptr;
  }
  if (::GetLastError() == ERROR_ALREADY_EXISTS) {
    ::CloseHandle(mutex);
    return INVALID_HANDLE_VALUE;
  }
  return mutex;
}

// 找到已在运行的那个实例的主窗口并提到前台；返回 false 表示窗口还没建立。
// 只匹配本程序的主窗口类，且跳过本进程自己的窗口（本进程还没有可显示的窗口）。
// Windows、LocalSend 等其他 Flutter 程序碰巧同名，因此不能用类名判断归属，窗口
// 所有权由上面的互斥体保证：同一登录会话里只有持有互斥体的那个进程在运行本程序。
inline bool FocusExistingInstanceWindow() {
  // EnumWindows 的回调不能捕获局部变量，用这个结构体携带上下文。
  struct SearchContext {
    DWORD self_process_id;
    HWND target;
  };
  SearchContext context{::GetCurrentProcessId(), nullptr};
  ::EnumWindows(
      [](HWND window, LPARAM param) -> BOOL {
        auto* context = reinterpret_cast<SearchContext*>(param);
        DWORD process_id = 0;
        ::GetWindowThreadProcessId(window, &process_id);
        if (process_id == context->self_process_id) {
          return TRUE;
        }
        if (::GetWindow(window, GW_OWNER) != nullptr) {
          return TRUE;  // 只认顶层主窗口，跳过模态对话框等附属窗口。
        }
        // 双击快捷方式时标题也应当存在，类名比标题更稳。
        wchar_t class_name[64] = {};
        if (::GetClassNameW(window, class_name,
                            static_cast<int>(sizeof(class_name) /
                                             sizeof(class_name[0]))) == 0) {
          return TRUE;
        }
        if (::lstrcmpW(class_name, kWindowClassName) != 0) {
          return TRUE;
        }
        // 优先挑已经显示出来的窗口：已有实例完全启动后它才可见。
        if (context->target == nullptr || ::IsWindowVisible(window)) {
          context->target = window;
        }
        if (::IsWindowVisible(window)) {
          return FALSE;
        }
        return TRUE;
      },
      reinterpret_cast<LPARAM>(&context));
  if (context.target == nullptr) {
    return false;
  }
  if (::IsIconic(context.target)) {
    ::ShowWindow(context.target, SW_RESTORE);
  }
  if (::SetForegroundWindow(context.target)) {
    return true;
  }
  // 系统前台锁拒绝了直接激活。把前台资格让给「任意进程」，再用置顶/取消置顶序列
  // 把已有窗口提到最前，最后退回任务栏闪烁，保证用户至少能看到窗口在哪。
  ::AllowSetForegroundWindow(ASFW_ANY);
  ::SetWindowPos(context.target, HWND_TOPMOST, 0, 0, 0, 0,
                 SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
  ::SetWindowPos(context.target, HWND_NOTOPMOST, 0, 0, 0, 0,
                 SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
  if (::SetForegroundWindow(context.target)) {
    return true;
  }
  ::FlashWindow(context.target, TRUE);
  return true;
}

#endif  // RUNNER_SINGLE_INSTANCE_H_
