#include <flutter/dart_project.h>
#include <flutter/flutter_view_controller.h>
#include <windows.h>

#include "flutter_window.h"
#include "single_instance.h"
#include "utils.h"

int APIENTRY wWinMain(_In_ HINSTANCE instance, _In_opt_ HINSTANCE prev,
                      _In_ wchar_t *command_line, _In_ int show_command) {
  // 禁止重复实例：同一登录会话里第二次启动不再开新窗口，只把已有窗口唤到前台。
  // 句柄刻意不关闭，进程退出（含崩溃）时由系统释放。
  HANDLE single_instance_mutex = ClaimSingleInstance();
  if (single_instance_mutex == INVALID_HANDLE_VALUE) {
    // 已有实例可能还在初始化、主窗口尚未建立，短暂重试等它出现；始终找不到就安静退出，
    // 不用模态对话框拖延本进程（对话框在无桌面或最小化场景下会变成卡住的隐藏窗口）。
    for (int attempt = 0; attempt < 10; ++attempt) {
      if (FocusExistingInstanceWindow()) {
        break;
      }
      ::Sleep(300);
    }
    return EXIT_SUCCESS;
  }

  // Attach to console when present (e.g., 'flutter run') or create a
  // new console when running with a debugger.
  if (!::AttachConsole(ATTACH_PARENT_PROCESS) && ::IsDebuggerPresent()) {
    CreateAndAttachConsole();
  }

  // Initialize COM, so that it is available for use in the library and/or
  // plugins.
  ::CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);

  flutter::DartProject project(L"data");

  std::vector<std::string> command_line_arguments =
      GetCommandLineArguments();

  project.set_dart_entrypoint_arguments(std::move(command_line_arguments));

  FlutterWindow window(project);
  Win32Window::Point origin(10, 10);
  Win32Window::Size size(1280, 720);
  // 窗口标题；源码为 UTF-8，由 CMake 的 /utf-8 保证正确解析。
  if (!window.Create(L"魔法裁判", origin, size)) {
    return EXIT_FAILURE;
  }
  window.SetQuitOnClose(true);

  ::MSG msg;
  while (::GetMessage(&msg, nullptr, 0, 0)) {
    ::TranslateMessage(&msg);
    ::DispatchMessage(&msg);
  }

  ::CoUninitialize();
  return EXIT_SUCCESS;
}
