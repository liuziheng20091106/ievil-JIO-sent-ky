#include "gui.h"

#include <commctrl.h>
#include <shlobj.h>

#include "install.h"
#include "system.h"
#include "version.h"

namespace upd {
namespace {

// ==== 控件编号 ====
enum ControlId {
  kIdBackendLabel = 100,
  kIdBackendEdit,
  kIdDirectoryLabel,
  kIdDirectoryEdit,
  kIdBrowse,
  kIdProgramFiles,
  kIdLaunch,
  kIdStatus,
  kIdProgress,
  kIdInstall,
  kIdCancel,
  kIdChoiceText,
  kIdChoiceUpdate,
  kIdChoiceUninstall,
  kIdChoiceQuit,
  kIdChoicePortable,
  kIdUninstallText,
  kIdUninstallList,
  kIdRemoveFiles,
  kIdRemoveData,
  kIdUninstallStart,
  kIdModeLabel,
  kIdModeInstall,
  kIdModePortable,
  kIdDesktopShortcut,
  kIdModeHint,
};

enum WindowMessage {
  kMessageProgress = WM_APP + 1,
  kMessageDone = WM_APP + 2,
};

constexpr int kWizardWidth = 640;
constexpr int kWizardHeight = 420;
constexpr int kChoiceWidth = 560;
constexpr int kChoiceHeight = 280;
constexpr int kUninstallWidth = 620;
constexpr int kUninstallHeight = 360;

HFONT UiFont() {
  static HFONT font = nullptr;
  if (font == nullptr) {
    NONCLIENTMETRICSW metrics{};
    metrics.cbSize = sizeof(metrics);
    if (::SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof(metrics), &metrics, 0)) {
      font = ::CreateFontIndirectW(&metrics.lfMessageFont);
    }
    if (font == nullptr) {
      font = static_cast<HFONT>(::GetStockObject(DEFAULT_GUI_FONT));
    }
  }
  return font;
}

bool RegisterWindowClass(const wchar_t* name, WNDPROC procedure) {
  WNDCLASSEXW description{};
  description.cbSize = sizeof(description);
  description.lpfnWndProc = procedure;
  description.hInstance = ::GetModuleHandleW(nullptr);
  description.hCursor = ::LoadCursorW(nullptr, IDC_ARROW);
  description.hbrBackground = reinterpret_cast<HBRUSH>(static_cast<INT_PTR>(COLOR_BTNFACE + 1));
  description.lpszClassName = name;
  description.hIcon = ::LoadIconW(nullptr, IDI_APPLICATION);
  description.hIconSm = description.hIcon;
  if (::RegisterClassExW(&description) != 0) {
    return true;
  }
  return ::GetLastError() == ERROR_CLASS_ALREADY_EXISTS;
}

HWND CreateChild(HWND parent, const wchar_t* className, const wchar_t* text, DWORD style, int x,
                 int y, int width, int height, int id) {
  const HWND child = ::CreateWindowExW(
      0, className, text, WS_CHILD | WS_VISIBLE | style, x, y, width, height, parent,
      reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)), ::GetModuleHandleW(nullptr), nullptr);
  if (child != nullptr) {
    ::SendMessageW(child, WM_SETFONT, reinterpret_cast<WPARAM>(UiFont()), TRUE);
  }
  return child;
}

void CenterWindow(HWND window, int width, int height) {
  const int screenWidth = ::GetSystemMetrics(SM_CXSCREEN);
  const int screenHeight = ::GetSystemMetrics(SM_CYSCREEN);
  ::SetWindowPos(window, nullptr, (screenWidth - width) / 2, (screenHeight - height) / 2, width,
                 height, SWP_NOZORDER | SWP_NOACTIVATE);
}

int RunMessageLoop(HWND window) {
  MSG message;
  while (::GetMessageW(&message, nullptr, 0, 0) != 0) {
    if (window != nullptr && ::IsDialogMessageW(window, &message)) {
      continue;
    }
    ::TranslateMessage(&message);
    ::DispatchMessageW(&message);
  }
  return 0;
}

// ==== 「已经装过了」选择窗口 ====

struct ChoiceState {
  int result = kInstalledChoiceQuit;
};

LRESULT CALLBACK ChoiceProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
  ChoiceState* state =
      reinterpret_cast<ChoiceState*>(::GetWindowLongPtrW(window, GWLP_USERDATA));
  switch (message) {
    case WM_CREATE: {
      const CREATESTRUCTW* create = reinterpret_cast<const CREATESTRUCTW*>(lparam);
      state = reinterpret_cast<ChoiceState*>(create->lpCreateParams);
      ::SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(state));
      CreateChild(window, L"STATIC", L"检测到本机已经安装过魔法裁判：", SS_LEFT, 20, 18, 500, 22,
                  kIdChoiceText);
      CreateChild(window, L"STATIC", create->lpszName, SS_LEFT, 20, 46, 500, 22, kIdChoiceText + 1000);
      CreateChild(window, L"STATIC",
                  L"请选择要执行的操作。「更新到最新」会下载并覆盖当前安装；「下载便携版」只把整包"
                  L"解压到你指定的目录，不动现有安装；「卸载」会删除程序文件与快捷方式"
                  L"（Updater.exe 自身保留）。",
                  SS_LEFT, 20, 76, 500, 56, kIdChoiceText + 1001);
      CreateChild(window, L"BUTTON", L"更新到最新", BS_DEFPUSHBUTTON | WS_TABSTOP, 40, 156, 110, 30,
                  kIdChoiceUpdate);
      CreateChild(window, L"BUTTON", L"下载便携版", BS_PUSHBUTTON | WS_TABSTOP, 160, 156, 110, 30,
                  kIdChoicePortable);
      CreateChild(window, L"BUTTON", L"卸载", BS_PUSHBUTTON | WS_TABSTOP, 280, 156, 110, 30,
                  kIdChoiceUninstall);
      CreateChild(window, L"BUTTON", L"退出", BS_PUSHBUTTON | WS_TABSTOP, 400, 156, 110, 30,
                  kIdChoiceQuit);
      return 0;
    }
    case WM_COMMAND: {
      const int id = static_cast<int>(LOWORD(wparam));
      if (state == nullptr) {
        return 0;
      }
      if (id == kIdChoiceUpdate) {
        state->result = kInstalledChoiceUpdate;
      } else if (id == kIdChoiceUninstall) {
        state->result = kInstalledChoiceUninstall;
      } else if (id == kIdChoicePortable) {
        state->result = kInstalledChoicePortable;
      } else {
        state->result = kInstalledChoiceQuit;
      }
      ::DestroyWindow(window);
      return 0;
    }
    case WM_CLOSE:
      if (state != nullptr) {
        state->result = kInstalledChoiceQuit;
      }
      ::DestroyWindow(window);
      return 0;
    case WM_DESTROY:
      ::PostQuitMessage(0);
      return 0;
    default:
      break;
  }
  return ::DefWindowProcW(window, message, wparam, lparam);
}

// ==== 安装向导 ====

std::wstring ReadWindowText(HWND control);

struct WizardState {
  HWND window = nullptr;
  HWND backendEdit = nullptr;
  HWND directoryEdit = nullptr;
  HWND programFilesCheck = nullptr;
  HWND launchCheck = nullptr;
  HWND statusLabel = nullptr;
  HWND progressBar = nullptr;
  HWND installButton = nullptr;
  HWND cancelButton = nullptr;
  HWND modeInstallRadio = nullptr;
  HWND modePortableRadio = nullptr;
  HWND modeHint = nullptr;
  HWND desktopShortcutCheck = nullptr;
  HANDLE thread = nullptr;
  std::wstring directory;
  // 三种自动填的目录：用户没自己改过时，切换安装/便携模式跟着换。
  std::wstring installDefaultDir;
  std::wstring portableDefaultDir;
  std::wstring programFilesDir;
  bool programFiles = false;
  bool launch = true;
  bool portable = false;
  bool desktopShortcut = true;
  int result = kExitOk;  // 用户直接关窗口＝什么都没做
};

// 目录框当前值是不是「自动填的三种之一」（是就允许切换模式时改写）。
bool DirectoryIsAutomatic(const WizardState* state, const std::wstring& value) {
  return _wcsicmp(value.c_str(), state->installDefaultDir.c_str()) == 0 ||
         _wcsicmp(value.c_str(), state->portableDefaultDir.c_str()) == 0 ||
         _wcsicmp(value.c_str(), state->programFilesDir.c_str()) == 0;
}

void ApplyWizardMode(HWND window, WizardState* state, bool portable) {
  state->portable = portable;
  ::EnableWindow(state->programFilesCheck, portable ? FALSE : TRUE);
  ::EnableWindow(state->desktopShortcutCheck, portable ? FALSE : TRUE);
  if (state->modeHint != nullptr) {
    ::SetWindowTextW(state->modeHint,
                     portable ? L"便携版：把整包解压到上面的目录，不写注册表、不建快捷方式，"
                                L"也没有卸载入口；换电脑直接拷走整个文件夹即可。"
                              : L"安装：装到上面的目录，创建开始菜单快捷方式"
                                L"（含「卸载魔法裁判」入口），桌面快捷方式可选，"
                                L"并准备好应用内静默更新。");
  }
  if (state->installButton != nullptr) {
    ::SetWindowTextW(state->installButton, portable ? L"开始下载" : L"开始安装");
  }
  // 目录还是自动值时跟着模式换；用户自己填过就不动他填的路径。
  const std::wstring current = Trim(ReadWindowText(state->directoryEdit));
  if (DirectoryIsAutomatic(state, current)) {
    ::SetWindowTextW(state->directoryEdit,
                     (portable ? state->portableDefaultDir : state->installDefaultDir).c_str());
  }
  (void)window;
}

void WizardProgress(void* context, int percent, const std::wstring& message) {
  WizardState* state = static_cast<WizardState*>(context);
  if (state == nullptr || state->window == nullptr) {
    return;
  }
  std::wstring* text = new std::wstring(message);
  if (::PostMessageW(state->window, kMessageProgress,
                     static_cast<WPARAM>(static_cast<INT_PTR>(percent)),
                     reinterpret_cast<LPARAM>(text)) == FALSE) {
    delete text;
  }
}

std::wstring ReadWindowText(HWND control) {
  const int length = ::GetWindowTextLengthW(control);
  if (length <= 0) {
    return std::wstring();
  }
  std::vector<wchar_t> buffer(static_cast<size_t>(length) + 1, L'\0');
  ::GetWindowTextW(control, buffer.data(), length + 1);
  return std::wstring(buffer.data());
}

DWORD WINAPI WizardThread(LPVOID parameter) {
  WizardState* state = static_cast<WizardState*>(parameter);
  Options options;
  options.command = L"install";
  options.from = ReadWindowText(state->backendEdit);
  options.dir = state->directory;
  options.portable = state->portable;
  options.desktopShortcut = state->desktopShortcut;
  // 便携版不往 Program Files 里装（目录由用户在界面上选）。
  options.toProgramFiles = state->portable ? false : state->programFiles;
  options.noLaunch = true;  // 启动由界面负责，提权后的子进程不再启动一次
  ProgressSink sink;
  sink.report = &WizardProgress;
  sink.context = state;
  state->result = RunInstall(options, &sink);
  ::PostMessageW(state->window, kMessageDone, static_cast<WPARAM>(state->result), 0);
  return 0;
}

void BeginInstall(HWND window, WizardState* state) {
  const std::wstring backend = Trim(ReadWindowText(state->backendEdit));
  if (backend.empty()) {
    ::MessageBoxW(window, L"请填写后端地址。", L"魔法裁判 安装向导", MB_OK | MB_ICONWARNING);
    return;
  }
  const std::wstring directory = Trim(ReadWindowText(state->directoryEdit));
  if (directory.empty()) {
    ::MessageBoxW(window, L"请填写安装目录。", L"魔法裁判 安装向导", MB_OK | MB_ICONWARNING);
    return;
  }
  state->directory = TrimTrailingSlash(directory);
  state->portable =
      ::SendMessageW(state->modePortableRadio, BM_GETCHECK, 0, 0) == BST_CHECKED;
  state->programFiles = ::SendMessageW(state->programFilesCheck, BM_GETCHECK, 0, 0) == BST_CHECKED;
  state->desktopShortcut =
      ::SendMessageW(state->desktopShortcutCheck, BM_GETCHECK, 0, 0) == BST_CHECKED;
  state->launch = ::SendMessageW(state->launchCheck, BM_GETCHECK, 0, 0) == BST_CHECKED;

  ::EnableWindow(state->installButton, FALSE);
  ::EnableWindow(state->backendEdit, FALSE);
  ::EnableWindow(state->directoryEdit, FALSE);
  ::EnableWindow(state->programFilesCheck, FALSE);
  ::EnableWindow(state->desktopShortcutCheck, FALSE);
  ::EnableWindow(state->modeInstallRadio, FALSE);
  ::EnableWindow(state->modePortableRadio, FALSE);
  ::SetWindowTextW(state->statusLabel,
                   state->portable ? L"正在准备下载便携版……" : L"正在准备安装……");
  state->thread = ::CreateThread(nullptr, 0, &WizardThread, state, 0, nullptr);
  if (state->thread == nullptr) {
    ::EnableWindow(state->installButton, TRUE);
    ::MessageBoxW(window, L"无法创建工作线程。", L"魔法裁判 安装向导", MB_OK | MB_ICONERROR);
  }
}

LRESULT CALLBACK WizardProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
  WizardState* state =
      reinterpret_cast<WizardState*>(::GetWindowLongPtrW(window, GWLP_USERDATA));
  switch (message) {
    case WM_CREATE: {
      const CREATESTRUCTW* create = reinterpret_cast<const CREATESTRUCTW*>(lparam);
      state = reinterpret_cast<WizardState*>(create->lpCreateParams);
      state->window = window;
      ::SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(state));

      CreateChild(window, L"STATIC", L"后端地址", SS_LEFT, 20, 20, 90, 22, kIdBackendLabel);
      state->backendEdit = CreateChild(window, L"EDIT", create->lpszName,
                                       WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP, 120, 18, 480, 24,
                                       kIdBackendEdit);
      CreateChild(window, L"STATIC", L"安装目录", SS_LEFT, 20, 56, 90, 22, kIdDirectoryLabel);
      state->directoryEdit = CreateChild(window, L"EDIT", state->directory.c_str(),
                                         WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP, 120, 54, 370, 24,
                                         kIdDirectoryEdit);
      CreateChild(window, L"BUTTON", L"浏览…", BS_PUSHBUTTON | WS_TABSTOP, 500, 54, 100, 24,
                  kIdBrowse);
      state->programFilesCheck =
          CreateChild(window, L"BUTTON", L"安装到 Program Files（需要管理员权限）",
                      BS_AUTOCHECKBOX | WS_TABSTOP, 120, 88, 400, 22, kIdProgramFiles);
      state->launchCheck = CreateChild(window, L"BUTTON", L"安装完成后启动魔法裁判",
                                       BS_AUTOCHECKBOX | WS_TABSTOP, 120, 114, 400, 22, kIdLaunch);
      ::SendMessageW(state->launchCheck, BM_SETCHECK, BST_CHECKED, 0);

      // 两种方式：安装（带快捷方式与卸载入口）或只下载便携版。
      CreateChild(window, L"STATIC", L"选择方式", SS_LEFT, 20, 152, 90, 22, kIdModeLabel);
      state->modeInstallRadio =
          CreateChild(window, L"BUTTON", L"安装（推荐）",
                      BS_AUTORADIOBUTTON | WS_GROUP | WS_TABSTOP, 120, 150, 160, 22, kIdModeInstall);
      state->modePortableRadio =
          CreateChild(window, L"BUTTON", L"仅下载便携版",
                      BS_AUTORADIOBUTTON | WS_TABSTOP, 290, 150, 160, 22, kIdModePortable);
      state->modeHint = CreateChild(window, L"STATIC", L"", SS_LEFT, 120, 176, 480, 40, kIdModeHint);
      state->desktopShortcutCheck =
          CreateChild(window, L"BUTTON", L"创建桌面快捷方式（可选；开始菜单快捷方式总是创建）",
                      BS_AUTOCHECKBOX | WS_TABSTOP, 120, 220, 480, 22, kIdDesktopShortcut);
      ::SendMessageW(state->desktopShortcutCheck, BM_SETCHECK, BST_CHECKED, 0);
      ::SendMessageW(state->portable ? state->modePortableRadio : state->modeInstallRadio,
                     BM_SETCHECK, BST_CHECKED, 0);

      state->statusLabel = CreateChild(
          window, L"STATIC", L"选好方式后点「开始安装」下载并安装最新版本。", SS_LEFT, 20, 256, 580,
          40, kIdStatus);
      state->progressBar = CreateChild(window, PROGRESS_CLASS, L"", WS_BORDER, 20, 306, 580, 22,
                                       kIdProgress);
      if (state->progressBar != nullptr) {
        ::SendMessageW(state->progressBar, PBM_SETRANGE32, 0, 100);
      }
      state->installButton = CreateChild(window, L"BUTTON", L"开始安装",
                                         BS_DEFPUSHBUTTON | WS_TABSTOP, 380, 351, 100, 30,
                                         kIdInstall);
      state->cancelButton =
          CreateChild(window, L"BUTTON", L"取消", BS_PUSHBUTTON | WS_TABSTOP, 500, 351, 100, 30,
                      kIdCancel);
      ApplyWizardMode(window, state, state->portable);
      return 0;
    }
    case WM_COMMAND: {
      const int id = static_cast<int>(LOWORD(wparam));
      if (state == nullptr) {
        return 0;
      }
      if (id == kIdInstall) {
        BeginInstall(window, state);
        return 0;
      }
      if (id == kIdModeInstall || id == kIdModePortable) {
        ApplyWizardMode(window, state, id == kIdModePortable);
        return 0;
      }
      if (id == kIdCancel && state->thread == nullptr) {
        ::DestroyWindow(window);
        return 0;
      }
      if (id == kIdBrowse) {
        BROWSEINFOW browse{};
        browse.hwndOwner = window;
        browse.lpszTitle = L"选择魔法裁判的安装目录";
        browse.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
        LPITEMIDLIST item = ::SHBrowseForFolderW(&browse);
        if (item != nullptr) {
          wchar_t path[MAX_PATH] = L"";
          if (::SHGetPathFromIDListW(item, path)) {
            ::SetWindowTextW(state->directoryEdit, path);
          }
          ::ILFree(item);
        }
        return 0;
      }
      if (id == kIdProgramFiles) {
        const bool checked =
            ::SendMessageW(state->programFilesCheck, BM_GETCHECK, 0, 0) == BST_CHECKED;
        if (checked) {
          ::SetWindowTextW(state->directoryEdit,
                           JoinPath(ProgramFilesDir(), kProductDirName).c_str());
        }
        return 0;
      }
      return 0;
    }
    case kMessageProgress: {
      std::wstring* text = reinterpret_cast<std::wstring*>(lparam);
      if (text != nullptr) {
        if (state != nullptr && state->statusLabel != nullptr) {
          ::SetWindowTextW(state->statusLabel, text->c_str());
        }
        delete text;
      }
      if (state != nullptr && state->progressBar != nullptr) {
        const int percent = static_cast<int>(static_cast<INT_PTR>(wparam));
        if (percent >= 0) {
          ::SendMessageW(state->progressBar, PBM_SETPOS, static_cast<WPARAM>(percent), 0);
        }
      }
      return 0;
    }
    case kMessageDone: {
      if (state == nullptr) {
        return 0;
      }
      if (state->thread != nullptr) {
        ::WaitForSingleObject(state->thread, 10000);
        ::CloseHandle(state->thread);
        state->thread = nullptr;
      }
      const int result = static_cast<int>(static_cast<INT_PTR>(wparam));
      if (result == kExitOk) {
        if (state->launch) {
          LaunchApplication(JoinPath(state->directory, kAppExeName), state->directory);
        }
        if (state->portable) {
          const std::wstring done =
              Format(L"便携版已下载到：\n%s\n\n直接运行里面的 %s 即可，不需要安装，"
                     L"也不会写入注册表或创建快捷方式。\n\n要打开这个文件夹吗？",
                     state->directory.c_str(), kAppExeName);
          if (::MessageBoxW(window, done.c_str(), L"魔法裁判 便携版",
                            MB_YESNO | MB_ICONINFORMATION) == IDYES) {
            ::ShellExecuteW(nullptr, L"open", state->directory.c_str(), nullptr, nullptr,
                            SW_SHOWNORMAL);
          }
        } else {
          const std::wstring done =
              state->desktopShortcut
                  ? std::wstring(L"魔法裁判已安装完成。\n\n已创建开始菜单与桌面快捷方式"
                                 L"（开始菜单里还有「卸载魔法裁判」）。")
                  : std::wstring(L"魔法裁判已安装完成。\n\n已创建开始菜单快捷方式"
                                 L"（里面还有「卸载魔法裁判」）。");
          ::MessageBoxW(window, done.c_str(), L"魔法裁判 安装向导", MB_OK | MB_ICONINFORMATION);
        }
      } else {
        ::MessageBoxW(window,
                      Format(L"安装没有完成（退出码 %d）。\n详细信息见 %s", result,
                             LogFilePath().c_str())
                          .c_str(),
                      L"魔法裁判 安装向导", MB_OK | MB_ICONERROR);
      }
      ::DestroyWindow(window);
      return 0;
    }
    case WM_CLOSE:
      if (state != nullptr && state->thread != nullptr) {
        ::MessageBoxW(window, L"正在安装，请等待完成。", L"魔法裁判 安装向导",
                      MB_OK | MB_ICONINFORMATION);
        return 0;
      }
      ::DestroyWindow(window);
      return 0;
    case WM_DESTROY:
      ::PostQuitMessage(0);
      return 0;
    default:
      break;
  }
  return ::DefWindowProcW(window, message, wparam, lparam);
}

// ==== 卸载向导 ====

struct UninstallState {
  HWND window = nullptr;
  HWND filesCheck = nullptr;
  HWND dataCheck = nullptr;
  HWND statusLabel = nullptr;
  HWND startButton = nullptr;
  HWND cancelButton = nullptr;
  HANDLE thread = nullptr;
  Options options;
  std::wstring directory;
  bool removeFiles = true;
  bool removeData = true;
  int result = kExitOk;
};

void UninstallProgress(void* context, int percent, const std::wstring& message) {
  UninstallState* state = static_cast<UninstallState*>(context);
  if (state == nullptr || state->window == nullptr) {
    return;
  }
  std::wstring* text = new std::wstring(message);
  if (::PostMessageW(state->window, kMessageProgress, static_cast<WPARAM>(percent),
                     reinterpret_cast<LPARAM>(text)) == FALSE) {
    delete text;
  }
}

DWORD WINAPI UninstallThread(LPVOID parameter) {
  UninstallState* state = static_cast<UninstallState*>(parameter);
  Options options = state->options;
  options.command = L"uninstall";
  options.dir = state->directory;
  options.skipProgramFiles = !state->removeFiles;
  options.purgeData = state->removeData;
  options.silent = true;
  ProgressSink sink;
  sink.report = &UninstallProgress;
  sink.context = state;
  const int result = RunUninstall(options, &sink);
  ::PostMessageW(state->window, kMessageDone, static_cast<WPARAM>(result), 0);
  return 0;
}

LRESULT CALLBACK UninstallProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
  UninstallState* state =
      reinterpret_cast<UninstallState*>(::GetWindowLongPtrW(window, GWLP_USERDATA));
  switch (message) {
    case WM_CREATE: {
      const CREATESTRUCTW* create = reinterpret_cast<const CREATESTRUCTW*>(lparam);
      state = reinterpret_cast<UninstallState*>(create->lpCreateParams);
      state->window = window;
      ::SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(state));

      CreateChild(window, L"STATIC", L"将删除以下内容：", SS_LEFT, 20, 16, 560, 22, kIdUninstallText);
      CreateChild(window, L"EDIT", create->lpszName,
                  WS_BORDER | ES_MULTILINE | ES_READONLY | WS_VSCROLL | ES_AUTOVSCROLL, 20, 42, 560,
                  150, kIdUninstallList);
      state->filesCheck =
          CreateChild(window, L"BUTTON", L"删除程序文件", BS_AUTOCHECKBOX | WS_TABSTOP, 20, 204, 260,
                      24, kIdRemoveFiles);
      state->dataCheck = CreateChild(window, L"BUTTON", L"删除持久化数据（存档与配置）",
                                     BS_AUTOCHECKBOX | WS_TABSTOP, 20, 232, 320, 24, kIdRemoveData);
      ::SendMessageW(state->filesCheck, BM_SETCHECK, BST_CHECKED, 0);
      ::SendMessageW(state->dataCheck, BM_SETCHECK, BST_CHECKED, 0);
      if (state->directory.empty()) {
        ::EnableWindow(state->filesCheck, FALSE);
      }
      state->statusLabel = CreateChild(window, L"STATIC", L"确认后开始卸载，Updater.exe 自身会保留。",
                                       SS_LEFT, 20, 264, 560, 22, kIdStatus);
      state->startButton = CreateChild(window, L"BUTTON", L"开始卸载",
                                       BS_DEFPUSHBUTTON | WS_TABSTOP, 360, 292, 100, 30,
                                       kIdUninstallStart);
      state->cancelButton = CreateChild(window, L"BUTTON", L"取消", BS_PUSHBUTTON | WS_TABSTOP, 480,
                                        292, 100, 30, kIdCancel);
      return 0;
    }
    case WM_COMMAND: {
      const int id = static_cast<int>(LOWORD(wparam));
      if (state == nullptr) {
        return 0;
      }
      if (id == kIdUninstallStart) {
        state->removeFiles =
            ::SendMessageW(state->filesCheck, BM_GETCHECK, 0, 0) == BST_CHECKED;
        state->removeData = ::SendMessageW(state->dataCheck, BM_GETCHECK, 0, 0) == BST_CHECKED;
        if (!state->removeFiles && !state->removeData) {
          ::MessageBoxW(window, L"两项都没有勾选，没有可删除的内容。", L"魔法裁判 卸载",
                        MB_OK | MB_ICONWARNING);
          return 0;
        }
        const UINT answer =
            ::MessageBoxW(window, L"确定要卸载吗？此操作不可撤销。", L"魔法裁判 卸载",
                          MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2);
        if (answer != IDYES) {
          return 0;
        }
        ::EnableWindow(state->startButton, FALSE);
        ::EnableWindow(state->cancelButton, FALSE);
        ::EnableWindow(state->filesCheck, FALSE);
        ::EnableWindow(state->dataCheck, FALSE);
        ::SetWindowTextW(state->statusLabel, L"正在卸载……");
        state->thread = ::CreateThread(nullptr, 0, &UninstallThread, state, 0, nullptr);
        if (state->thread == nullptr) {
          ::MessageBoxW(window, L"无法创建工作线程。", L"魔法裁判 卸载", MB_OK | MB_ICONERROR);
        }
        return 0;
      }
      if (id == kIdCancel && state->thread == nullptr) {
        ::DestroyWindow(window);
        return 0;
      }
      return 0;
    }
    case kMessageProgress: {
      std::wstring* text = reinterpret_cast<std::wstring*>(lparam);
      if (text != nullptr) {
        if (state != nullptr && state->statusLabel != nullptr) {
          ::SetWindowTextW(state->statusLabel, text->c_str());
        }
        delete text;
      }
      return 0;
    }
    case kMessageDone: {
      if (state == nullptr) {
        return 0;
      }
      if (state->thread != nullptr) {
        ::WaitForSingleObject(state->thread, 10000);
        ::CloseHandle(state->thread);
        state->thread = nullptr;
      }
      const int result = static_cast<int>(static_cast<INT_PTR>(wparam));
      if (result == kExitOk) {
        ::MessageBoxW(window, L"卸载完成，Updater.exe 自身已保留。", L"魔法裁判 卸载",
                      MB_OK | MB_ICONINFORMATION);
      } else {
        ::MessageBoxW(window, L"卸载完成，但有部分文件未能删除（可能仍在使用中）。",
                      L"魔法裁判 卸载", MB_OK | MB_ICONWARNING);
      }
      ::DestroyWindow(window);
      return 0;
    }
    case WM_CLOSE:
      if (state != nullptr && state->thread != nullptr) {
        return 0;
      }
      ::DestroyWindow(window);
      return 0;
    case WM_DESTROY:
      ::PostQuitMessage(0);
      return 0;
    default:
      break;
  }
  return ::DefWindowProcW(window, message, wparam, lparam);
}

std::wstring BuildUninstallSummary(const std::wstring& directory) {
  std::wstring text;
  if (directory.empty()) {
    text += L"没有检测到安装目录（只清理注册表、计划任务与持久化数据）。\r\n";
  } else {
    text += L"程序目录：" + directory + L"\r\n";
    std::vector<std::wstring> files;
    std::vector<std::wstring> directories;
    std::wstring error;
    if (ListTreeRelative(directory, &files, &directories, &error)) {
      size_t shown = 0;
      for (size_t index = 0; index < files.size() && shown < 20; ++index, ++shown) {
        text += L"  " + files[index] + L"\r\n";
      }
      if (files.size() > shown) {
        text += Format(L"  …… 另有 %llu 个文件\r\n",
                       static_cast<unsigned long long>(files.size() - shown));
      }
    }
  }
  const std::vector<std::wstring> dataDirs = PersistentDataDirs();
  text += L"\r\n持久化数据：\r\n";
  for (size_t index = 0; index < dataDirs.size(); ++index) {
    text += L"  " + dataDirs[index];
    text += DirExists(dataDirs[index]) ? L"（存在）\r\n" : L"（不存在）\r\n";
  }
  text += L"\r\n注册表：HKCU\\" + std::wstring(kRegistryProductKey) + L"\r\n";
  text += L"计划任务：" + std::wstring(kTaskName) + L"\r\n";
  return text;
}

}  // namespace

void ShowErrorDialog(const std::wstring& title, const std::wstring& text) {
  ::MessageBoxW(nullptr, text.c_str(), title.c_str(), MB_OK | MB_ICONERROR | MB_SETFOREGROUND);
}

void ShowInfoDialog(const std::wstring& title, const std::wstring& text) {
  ::MessageBoxW(nullptr, text.c_str(), title.c_str(),
                MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND);
}

int ShowInstalledChoiceDialog(const std::wstring& installDir, const std::wstring& version) {
  if (!RegisterWindowClass(L"MagicJudgeUpdaterChoice", &ChoiceProc)) {
    return kInstalledChoiceQuit;
  }
  ChoiceState state;
  std::wstring subtitle = L"安装目录：" + installDir;
  if (!version.empty()) {
    subtitle += L"    版本：" + version;
  }
  const std::wstring title = L"魔法裁判 检测到已有安装";
  HWND window = ::CreateWindowExW(WS_EX_DLGMODALFRAME, L"MagicJudgeUpdaterChoice", subtitle.c_str(),
                                  WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                                  CW_USEDEFAULT, CW_USEDEFAULT, kChoiceWidth, kChoiceHeight, nullptr,
                                  nullptr, ::GetModuleHandleW(nullptr), &state);
  if (window == nullptr) {
    return kInstalledChoiceQuit;
  }
  ::SetWindowTextW(window, title.c_str());
  CenterWindow(window, kChoiceWidth, kChoiceHeight);
  ::SetForegroundWindow(window);
  RunMessageLoop(window);
  return state.result;
}

int RunInstallWizard(const Options& options) {
  if (!RegisterWindowClass(L"MagicJudgeUpdaterWizard", &WizardProc)) {
    ShowErrorDialog(L"魔法裁判 安装向导", L"注册窗口类失败。");
    return kExitFailure;
  }
  ::InitCommonControls();
  INITCOMMONCONTROLSEX commonControls{};
  commonControls.dwSize = sizeof(commonControls);
  commonControls.dwICC = ICC_PROGRESS_CLASS;
  ::InitCommonControlsEx(&commonControls);
  WizardState state;
  // 三份自动目录：安装默认当前目录（或 --dir），便携版默认在其下建一个子目录，
  // 免得几百个文件直接散进用户选的目录里；--dir 明确给了就两个模式都用它。
  state.installDefaultDir =
      options.dir.empty() ? TrimTrailingSlash(CurrentDirectory()) : TrimTrailingSlash(options.dir);
  state.portableDefaultDir = options.dir.empty()
                                 ? JoinPath(state.installDefaultDir, kProductDirName)
                                 : state.installDefaultDir;
  state.programFilesDir = JoinPath(ProgramFilesDir(), kProductDirName);
  state.portable = options.portable;
  state.desktopShortcut = options.desktopShortcut;
  state.directory = state.portable ? state.portableDefaultDir : state.installDefaultDir;
  std::wstring backend = options.from.empty() ? std::wstring(kDefaultBackend) : options.from;
  const std::wstring title = L"魔法裁判 安装向导";
  HWND window = ::CreateWindowExW(0, L"MagicJudgeUpdaterWizard", backend.c_str(),
                                  WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                                  CW_USEDEFAULT, CW_USEDEFAULT, kWizardWidth, kWizardHeight, nullptr,
                                  nullptr, ::GetModuleHandleW(nullptr), &state);
  if (window == nullptr) {
    ShowErrorDialog(L"魔法裁判 安装向导", L"创建窗口失败。");
    return kExitFailure;
  }
  ::SetWindowTextW(window, title.c_str());
  CenterWindow(window, kWizardWidth, kWizardHeight);
  ::SetForegroundWindow(window);
  RunMessageLoop(window);
  return state.result;
}

int RunUninstallWizard(const Options& options) {
  if (!RegisterWindowClass(L"MagicJudgeUpdaterUninstall", &UninstallProc)) {
    ShowErrorDialog(L"魔法裁判 卸载", L"注册窗口类失败。");
    return kExitFailure;
  }
  InstallInfo info;
  DetectInstall(&info);
  UninstallState state;
  state.options = options;
  state.directory = options.dir.empty() ? TrimTrailingSlash(info.installDir)
                                        : TrimTrailingSlash(options.dir);
  const std::wstring summary = BuildUninstallSummary(state.directory);
  const std::wstring title = L"魔法裁判 卸载";
  HWND window = ::CreateWindowExW(0, L"MagicJudgeUpdaterUninstall", summary.c_str(),
                                  WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                                  CW_USEDEFAULT, CW_USEDEFAULT, kUninstallWidth, kUninstallHeight,
                                  nullptr, nullptr, ::GetModuleHandleW(nullptr), &state);
  if (window == nullptr) {
    ShowErrorDialog(L"魔法裁判 卸载", L"创建窗口失败。");
    return kExitFailure;
  }
  ::SetWindowTextW(window, title.c_str());
  CenterWindow(window, kUninstallWidth, kUninstallHeight);
  ::SetForegroundWindow(window);
  RunMessageLoop(window);
  return state.result;
}

int RunInstallerEntry(const Options& options) {
  InstallInfo info;
  const bool installed = DetectInstall(&info);
  if (!installed) {
    return RunInstallWizard(options);
  }
  const int choice = ShowInstalledChoiceDialog(info.installDir, info.version);
  if (choice == kInstalledChoiceUninstall) {
    Options uninstallOptions;
    uninstallOptions.command = L"uninstall";
    uninstallOptions.dir = info.installDir;
    return RunUninstallWizard(uninstallOptions);
  }
  if (choice == kInstalledChoicePortable) {
    // 只下载便携版：不清空目录字段，让向导用「便携版默认目录」。
    Options portableOptions = options;
    portableOptions.command = L"install";
    portableOptions.portable = true;
    portableOptions.dir.clear();
    return RunInstallWizard(portableOptions);
  }
  if (choice == kInstalledChoiceUpdate) {
    Options updateOptions = options;
    updateOptions.command = L"install";
    updateOptions.dir = info.installDir;
    return RunInstallWizard(updateOptions);
  }
  return kExitOk;
}

}  // namespace upd
