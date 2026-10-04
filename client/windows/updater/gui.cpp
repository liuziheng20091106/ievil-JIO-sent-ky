#include "gui.h"

#include <commctrl.h>
#include <shlobj.h>

#include <algorithm>

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
  kIdChoiceUpdate,
  kIdChoiceUninstall,
  kIdChoiceQuit,
  kIdChoicePortable,
  kIdUninstallText,
  kIdUninstallList,
  kIdRemoveFiles,
  kIdRemoveData,
  kIdUninstallStart,
  kIdModeInstall,
  kIdModePortable,
  kIdDesktopShortcut,
  kIdModeHint,
};

enum WindowMessage {
  kMessageProgress = WM_APP + 1,
  kMessageDone = WM_APP + 2,
};

// ==== 界面文案 ====
// 布局要按文字实测宽度算高度，切换方式时也要用同一份文字，所以统一放在一处。

const wchar_t* const kTextBackendLabel = L"后端地址";
const wchar_t* const kTextDirectoryLabel = L"安装目录";
const wchar_t* const kTextBrowse = L"浏览…";
const wchar_t* const kTextLocationGroup = L"安装位置";
const wchar_t* const kTextProgramFiles = L"安装到 Program Files（需要管理员权限）";
const wchar_t* const kTextLaunch = L"安装完成后启动魔法裁判";
const wchar_t* const kTextModeGroup = L"安装方式";
const wchar_t* const kTextModeInstall = L"安装（推荐）";
const wchar_t* const kTextModePortable = L"仅下载便携版";
const wchar_t* const kTextDesktopShortcut = L"创建桌面快捷方式（可选；开始菜单快捷方式总是创建）";
const wchar_t* const kTextInstallButton = L"开始安装";
const wchar_t* const kTextDownloadButton = L"开始下载";
const wchar_t* const kTextUninstallButton = L"开始卸载";
const wchar_t* const kTextCancelButton = L"取消";

// 两种方式各自的说明与初始提示：跟着选中的方式走，避免提示与按钮文字对不上。
const wchar_t* const kModeHintInstallText =
    L"安装：装到上面的目录，创建开始菜单快捷方式（含「卸载魔法裁判」入口），"
    L"桌面快捷方式可选，并准备好应用内更新。";
const wchar_t* const kModeHintPortableText =
    L"便携版：把整包解压到上面的目录，不写注册表、不建快捷方式，也没有卸载入口；"
    L"换电脑直接拷走整个文件夹即可。";
const wchar_t* const kStatusReadyInstall = L"确认无误后点「开始安装」，将下载并安装最新版本。";
const wchar_t* const kStatusReadyPortable = L"确认无误后点「开始下载」，只下载便携版，不改动现有安装。";
const wchar_t* const kStatusWorkingInstall = L"正在准备安装……";
const wchar_t* const kStatusWorkingPortable = L"正在准备下载便携版……";

// 「已经装过了」选择窗口与卸载窗口的文案。
const wchar_t* const kTextChoiceHeading = L"检测到本机已经安装过魔法裁判：";
const wchar_t* const kTextChoiceHint =
    L"请选择要执行的操作。「更新到最新」会下载并覆盖当前安装；"
    L"「下载便携版」只把整包解压到你指定的目录，不动现有安装；"
    L"「卸载」会删除程序文件与快捷方式（Updater.exe 自身保留）。";
const wchar_t* const kTextChoiceUpdate = L"更新到最新";
const wchar_t* const kTextChoicePortable = L"下载便携版";
const wchar_t* const kTextChoiceUninstall = L"卸载";
const wchar_t* const kTextChoiceQuit = L"退出";
const wchar_t* const kTextUninstallHeading = L"将删除以下内容：";
const wchar_t* const kTextRemoveFiles = L"删除程序文件";
const wchar_t* const kTextRemoveData = L"删除持久化数据（存档与配置）";
const wchar_t* const kTextUninstallReady = L"确认后开始卸载，Updater.exe 自身会保留。";

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

// ==== 布局度量 ====
//
// 界面尺寸不写字面像素值：统一按系统 DPI 缩放，行高与文字宽度按当前界面字体实测，
// 窗口高度由内容自上而下算出来。这样在高 DPI 或系统大字体下，控件既不会被裁掉，
// 也不会互相挤压（旧版把控件钉死在 640x420 里，底下的按钮正好被窗口下沿切掉）。

// 屏幕 DC 报出的就是本进程的真实 DPI（清单里声明了系统 DPI 感知）。
UINT ScreenDpi(HDC dc) {
  const int dpi = dc != nullptr ? ::GetDeviceCaps(dc, LOGPIXELSX) : 96;
  return dpi >= 72 && dpi <= 480 ? static_cast<UINT>(dpi) : 96;
}

// 测量期间把界面字体选进 DC，析构时还原。
struct FontSelection {
  HDC dc = nullptr;
  HGDIOBJ previous = nullptr;
  explicit FontSelection(HDC target) : dc(target) {
    if (dc != nullptr) {
      previous = ::SelectObject(dc, UiFont());
    }
  }
  ~FontSelection() {
    if (dc != nullptr && previous != nullptr) {
      ::SelectObject(dc, previous);
    }
  }
};

// 窗口还没建好时先在屏幕 DC 上量布局：窗口大小要用它算。
struct ScreenCanvas {
  HDC dc = nullptr;
  FontSelection font;
  ScreenCanvas() : dc(::GetDC(nullptr)), font(dc) {}
  ~ScreenCanvas() {
    if (dc != nullptr) {
      ::ReleaseDC(nullptr, dc);
    }
  }
};

int TextWidth(HDC dc, const std::wstring& text) {
  if (dc == nullptr || text.empty()) {
    return 0;
  }
  SIZE size{};
  ::GetTextExtentPoint32W(dc, text.c_str(), static_cast<int>(text.size()), &size);
  return size.cx;
}

int LineHeight(HDC dc) {
  if (dc == nullptr) {
    return 15;
  }
  TEXTMETRICW metrics{};
  ::GetTextMetricsW(dc, &metrics);
  return metrics.tmHeight + metrics.tmExternalLeading;
}

// 按控件宽度换行后的文字高度：静态文本的自动换行与 DT_WORDBREAK 一致。
int WrappedHeight(HDC dc, const std::wstring& text, int width) {
  if (dc == nullptr || width <= 0) {
    return 0;
  }
  RECT rect{0, 0, width, 0};
  ::DrawTextW(dc, text.c_str(), -1, &rect, DT_CALCRECT | DT_WORDBREAK | DT_NOPREFIX);
  return rect.bottom - rect.top;
}

// 一套缩放好的尺寸；字段都已经是像素值，不再二次缩放。
struct Layout {
  UINT dpi = 96;
  int textHeight = 15;
  int margin = 16;        // 窗口四周留白
  int sectionGap = 12;    // 区块之间
  int labelWidth = 72;    // 左列标签宽度
  int labelGap = 8;       // 标签与控件的间距
  int groupCaption = 17;  // 分组框标题占的高度
  int groupPadding = 10;  // 分组框内边距
  int groupBottom = 10;   // 分组框底部内边距
  int editHeight = 25;
  int buttonHeight = 28;
  int checkboxHeight = 21;
  int contentWidth = 580;

  int Scale(int pixels) const { return ::MulDiv(pixels, static_cast<int>(dpi), 96); }
  int left() const { return margin; }
  int right() const { return margin + contentWidth; }
  int innerLeft() const { return margin + groupPadding; }
  int innerRight() const { return margin + contentWidth - groupPadding; }
  int clientWidth() const { return contentWidth + 2 * margin; }
};

Layout BaseLayout(HDC dc) {
  Layout layout;
  layout.dpi = ScreenDpi(dc);
  layout.textHeight = LineHeight(dc);
  layout.margin = layout.Scale(16);
  layout.sectionGap = layout.Scale(12);
  layout.labelWidth = layout.Scale(72);
  layout.labelGap = layout.Scale(8);
  layout.groupCaption = layout.textHeight + layout.Scale(2);
  layout.groupPadding = layout.Scale(10);
  layout.groupBottom = layout.Scale(10);
  layout.editHeight = std::max(layout.Scale(24), layout.textHeight + layout.Scale(10));
  layout.buttonHeight = std::max(layout.Scale(28), layout.textHeight + layout.Scale(12));
  layout.checkboxHeight = std::max(layout.Scale(20), layout.textHeight + layout.Scale(6));
  layout.contentWidth = layout.Scale(580);
  return layout;
}

// 复选框要的宽度：方块 + 文字。
int CheckboxWidth(const Layout& layout, HDC dc, const std::wstring& text) {
  return layout.Scale(22) + TextWidth(dc, text);
}

// 让单行标签与相邻控件在竖直方向居中对齐。
RECT AlignLabel(const Layout& layout, int x, int y, int controlHeight, int width) {
  const int top = y + (controlHeight - layout.textHeight) / 2;
  return RECT{x, top, x + width, top + layout.textHeight};
}

HWND CreateChildRect(HWND parent, const wchar_t* className, const wchar_t* text, DWORD style,
                     const RECT& rect, int id) {
  return CreateChild(parent, className, text, style, rect.left, rect.top, rect.right - rect.left,
                     rect.bottom - rect.top, id);
}

// 按客户区尺寸算窗口尺寸（含标题栏与边框），保证客户区正好放得下布局。
SIZE WindowSizeForClient(int clientWidth, int clientHeight) {
  RECT rect{0, 0, clientWidth, clientHeight};
  ::AdjustWindowRectEx(&rect, WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU, FALSE, 0);
  SIZE size{};
  size.cx = rect.right - rect.left;
  size.cy = rect.bottom - rect.top;
  return size;
}

// ==== 「已经装过了」选择窗口 ====

struct ChoiceLayout {
  RECT heading;
  RECT subtitle;
  RECT hint;
  RECT update;
  RECT portable;
  RECT uninstall;
  RECT quit;
  int clientWidth = 0;
  int clientHeight = 0;
};

ChoiceLayout ComputeChoiceLayout(HDC dc, const std::wstring& subtitle) {
  Layout layout = BaseLayout(dc);
  const int buttonGap = layout.Scale(10);
  int textWidth = TextWidth(dc, kTextChoiceUpdate);
  textWidth = std::max(textWidth, TextWidth(dc, kTextChoicePortable));
  textWidth = std::max(textWidth, TextWidth(dc, kTextChoiceUninstall));
  textWidth = std::max(textWidth, TextWidth(dc, kTextChoiceQuit));
  const int buttonWidth = std::max(layout.Scale(96), textWidth + layout.Scale(28));
  const int buttonRow = 4 * buttonWidth + 3 * buttonGap;
  layout.contentWidth = std::max(layout.Scale(520), buttonRow);

  ChoiceLayout result;
  const int left = layout.left();
  const int right = layout.right();
  int y = layout.margin;

  result.heading = RECT{left, y, right, y + layout.textHeight};
  y += layout.textHeight + layout.Scale(6);
  // 安装目录可能很长：让它换行，高度按实测给，别把后面的版本号挤掉。
  const int subtitleHeight = std::max(layout.textHeight, WrappedHeight(dc, subtitle, layout.contentWidth));
  result.subtitle = RECT{left, y, right, y + subtitleHeight};
  y += subtitleHeight + layout.Scale(12);
  const int hintHeight = WrappedHeight(dc, kTextChoiceHint, layout.contentWidth);
  result.hint = RECT{left, y, right, y + hintHeight};
  y += hintHeight + layout.Scale(18);

  // 四个按钮等宽排在右下角。
  const int rowLeft = right - buttonRow;
  result.update = RECT{rowLeft, y, rowLeft + buttonWidth, y + layout.buttonHeight};
  result.portable = RECT{result.update.right + buttonGap, y,
                         result.update.right + buttonGap + buttonWidth, y + layout.buttonHeight};
  result.uninstall = RECT{result.portable.right + buttonGap, y,
                          result.portable.right + buttonGap + buttonWidth, y + layout.buttonHeight};
  result.quit = RECT{result.uninstall.right + buttonGap, y,
                     result.uninstall.right + buttonGap + buttonWidth, y + layout.buttonHeight};
  y += layout.buttonHeight + layout.margin;

  result.clientWidth = layout.clientWidth();
  result.clientHeight = y;
  return result;
}

struct ChoiceState {
  ChoiceLayout layout;
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
      const ChoiceLayout& layout = state->layout;
      CreateChildRect(window, L"STATIC", kTextChoiceHeading, SS_LEFT, layout.heading, 0);
      CreateChildRect(window, L"STATIC", create->lpszName, SS_LEFT, layout.subtitle, 0);
      CreateChildRect(window, L"STATIC", kTextChoiceHint, SS_LEFT, layout.hint, 0);
      CreateChildRect(window, L"BUTTON", kTextChoiceUpdate, BS_DEFPUSHBUTTON | WS_TABSTOP,
                      layout.update, kIdChoiceUpdate);
      CreateChildRect(window, L"BUTTON", kTextChoicePortable, BS_PUSHBUTTON | WS_TABSTOP,
                      layout.portable, kIdChoicePortable);
      CreateChildRect(window, L"BUTTON", kTextChoiceUninstall, BS_PUSHBUTTON | WS_TABSTOP,
                      layout.uninstall, kIdChoiceUninstall);
      CreateChildRect(window, L"BUTTON", kTextChoiceQuit, BS_PUSHBUTTON | WS_TABSTOP, layout.quit,
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

struct WizardLayout {
  RECT backendLabel;
  RECT backendEdit;
  RECT locationGroup;
  RECT directoryLabel;
  RECT directoryEdit;
  RECT browse;
  RECT programFiles;
  RECT modeGroup;
  RECT modeInstall;
  RECT modePortable;
  RECT modeHint;
  RECT desktopShortcut;
  RECT launch;
  RECT status;
  RECT progress;
  RECT install;
  RECT cancel;
  int clientWidth = 0;
  int clientHeight = 0;
};

WizardLayout ComputeWizardLayout(HDC dc) {
  Layout layout = BaseLayout(dc);
  const int browseWidth = std::max(layout.Scale(84), TextWidth(dc, kTextBrowse) + layout.Scale(26));
  // 宽度按最宽的一行内容撑开：高 DPI 或系统大字体下也不会把字裁掉。
  int required = layout.Scale(580);
  required = std::max(required,
                      CheckboxWidth(layout, dc, kTextProgramFiles) + 2 * layout.groupPadding);
  required = std::max(required,
                      CheckboxWidth(layout, dc, kTextDesktopShortcut) + 2 * layout.groupPadding);
  required = std::max(required, layout.labelWidth + layout.labelGap + layout.Scale(260));
  required = std::max(required, 2 * layout.groupPadding + layout.labelWidth + layout.labelGap +
                                    layout.Scale(300) + layout.labelGap + browseWidth);
  layout.contentWidth = required;

  WizardLayout result;
  const int left = layout.left();
  const int right = layout.right();
  const int innerLeft = layout.innerLeft();
  const int innerRight = layout.innerRight();
  int y = layout.margin;

  // 后端地址。
  result.backendLabel = AlignLabel(layout, left, y, layout.editHeight, layout.labelWidth);
  result.backendEdit =
      RECT{left + layout.labelWidth + layout.labelGap, y, right, y + layout.editHeight};
  y += layout.editHeight + layout.sectionGap;

  // 安装位置：目录框 + 浏览按钮 + Program Files 选项。
  result.locationGroup = RECT{left, y, right, 0};
  int cursor = y + layout.groupCaption;
  const int directoryLeft = innerLeft + layout.labelWidth + layout.labelGap;
  result.directoryLabel = AlignLabel(layout, innerLeft, cursor, layout.editHeight, layout.labelWidth);
  result.directoryEdit = RECT{directoryLeft, cursor, innerRight - browseWidth - layout.labelGap,
                              cursor + layout.editHeight};
  result.browse = RECT{innerRight - browseWidth, cursor, innerRight, cursor + layout.editHeight};
  cursor += layout.editHeight + layout.Scale(8);
  result.programFiles = RECT{innerLeft, cursor, innerRight, cursor + layout.checkboxHeight};
  cursor += layout.checkboxHeight + layout.groupBottom;
  result.locationGroup.bottom = cursor;
  y = cursor + layout.sectionGap;

  // 安装方式：两种方式 + 说明 + 桌面快捷方式。
  result.modeGroup = RECT{left, y, right, 0};
  cursor = y + layout.groupCaption;
  const int installWidth = CheckboxWidth(layout, dc, kTextModeInstall);
  const int portableWidth = CheckboxWidth(layout, dc, kTextModePortable);
  result.modeInstall =
      RECT{innerLeft, cursor, innerLeft + installWidth, cursor + layout.checkboxHeight};
  result.modePortable = RECT{innerLeft + installWidth + layout.Scale(24), cursor,
                             innerLeft + installWidth + layout.Scale(24) + portableWidth,
                             cursor + layout.checkboxHeight};
  cursor += layout.checkboxHeight + layout.Scale(6);
  // 说明文字的高度按换行后的实测值取，两种方式里取高的那个，切换时高度不跳。
  const int hintHeight = std::max(WrappedHeight(dc, kModeHintInstallText, innerRight - innerLeft),
                                  WrappedHeight(dc, kModeHintPortableText, innerRight - innerLeft));
  result.modeHint = RECT{innerLeft, cursor, innerRight, cursor + hintHeight};
  cursor += hintHeight + layout.Scale(8);
  result.desktopShortcut = RECT{innerLeft, cursor, innerRight, cursor + layout.checkboxHeight};
  cursor += layout.checkboxHeight + layout.groupBottom;
  result.modeGroup.bottom = cursor;
  y = cursor + layout.sectionGap;

  // 安装完成后是否启动。
  result.launch = RECT{left, y, right, y + layout.checkboxHeight};
  y += layout.checkboxHeight + layout.sectionGap;

  // 状态文字留两行，进度条通栏。
  result.status = RECT{left, y, right, y + 2 * layout.textHeight + layout.Scale(2)};
  y += (result.status.bottom - result.status.top) + layout.Scale(8);
  result.progress = RECT{left, y, right, y + layout.Scale(20)};
  y += layout.Scale(20) + layout.Scale(16);

  // 右下角两个等宽按钮。
  int buttonText = std::max(TextWidth(dc, kTextInstallButton), TextWidth(dc, kTextDownloadButton));
  buttonText = std::max(buttonText, TextWidth(dc, kTextCancelButton));
  const int buttonWidth = std::max(layout.Scale(96), buttonText + layout.Scale(28));
  const int buttonGap = layout.Scale(10);
  result.cancel = RECT{right - buttonWidth, y, right, y + layout.buttonHeight};
  result.install = RECT{right - 2 * buttonWidth - buttonGap, y, right - buttonWidth - buttonGap,
                        y + layout.buttonHeight};
  y += layout.buttonHeight + layout.margin;

  result.clientWidth = layout.clientWidth();
  result.clientHeight = y;
  return result;
}

struct WizardState {
  WizardLayout layout;
  Options updateOptions;
  HWND window = nullptr;
  HWND backendEdit = nullptr;
  HWND directoryEdit = nullptr;
  HWND browseButton = nullptr;
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
    ::SetWindowTextW(state->modeHint, portable ? kModeHintPortableText : kModeHintInstallText);
  }
  if (state->installButton != nullptr) {
    ::SetWindowTextW(state->installButton, portable ? kTextDownloadButton : kTextInstallButton);
  }
  // 状态提示跟着方式走，免得提示里的按钮名和按钮上的文字对不上。
  if (state->statusLabel != nullptr && state->thread == nullptr) {
    ::SetWindowTextW(state->statusLabel, portable ? kStatusReadyPortable : kStatusReadyInstall);
  }
  // 目录还是自动值时跟着模式换；用户自己填过就不动他填的路径。
  const std::wstring current = Trim(ReadWindowText(state->directoryEdit));
  if (DirectoryIsAutomatic(state, current)) {
    ::SetWindowTextW(state->directoryEdit,
                     (portable ? state->portableDefaultDir : state->installDefaultDir).c_str());
  }
  (void)window;
}

// 安装进行中把整张表单一起禁掉：不再留下「看着能点、点了没反应」的控件。
void SetWizardBusy(WizardState* state, bool busy) {
  HWND controls[] = {state->backendEdit,         state->directoryEdit,
                     state->browseButton,        state->programFilesCheck,
                     state->desktopShortcutCheck, state->launchCheck,
                     state->modeInstallRadio,    state->modePortableRadio,
                     state->installButton,       state->cancelButton};
  for (HWND control : controls) {
    if (control != nullptr) {
      ::EnableWindow(control, busy ? FALSE : TRUE);
    }
  }
  if (!busy) {
    // 便携版用不到这两项，收工后按当前方式恢复。
    ::EnableWindow(state->programFilesCheck, state->portable ? FALSE : TRUE);
    ::EnableWindow(state->desktopShortcutCheck, state->portable ? FALSE : TRUE);
  }
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
  if (!state->updateOptions.command.empty()) {
    ProgressSink sink;
    sink.report = &WizardProgress;
    sink.context = state;
    state->result = state->updateOptions.command == L"task-entry"
                        ? RunTaskEntry(state->updateOptions, &sink)
                        : RunUpdateApp(state->updateOptions, &sink);
    ::PostMessageW(state->window, kMessageDone, static_cast<WPARAM>(state->result), 0);
    return 0;
  }
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

  SetWizardBusy(state, true);
  ::SetWindowTextW(state->statusLabel,
                   state->portable ? kStatusWorkingPortable : kStatusWorkingInstall);
  state->thread = ::CreateThread(nullptr, 0, &WizardThread, state, 0, nullptr);
  if (state->thread == nullptr) {
    SetWizardBusy(state, false);
    ::SetWindowTextW(state->statusLabel,
                     state->portable ? kStatusReadyPortable : kStatusReadyInstall);
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
      const WizardLayout& layout = state->layout;
      if (!state->updateOptions.command.empty()) {
        state->statusLabel = CreateChildRect(window, L"STATIC", L"正在准备更新……", SS_LEFT,
                                              layout.status, kIdStatus);
        state->progressBar = CreateChildRect(window, PROGRESS_CLASS, L"", WS_BORDER,
                                              layout.progress, kIdProgress);
        ::SendMessageW(state->progressBar, PBM_SETRANGE32, 0, 100);
        state->thread = ::CreateThread(nullptr, 0, &WizardThread, state, 0, nullptr);
        if (state->thread == nullptr) {
          state->result = kExitFailure;
          ::PostMessageW(window, kMessageDone, static_cast<WPARAM>(state->result), 0);
        }
        return 0;
      }

      CreateChildRect(window, L"STATIC", kTextBackendLabel, SS_LEFT, layout.backendLabel,
                      kIdBackendLabel);
      state->backendEdit =
          CreateChildRect(window, L"EDIT", create->lpszName,
                          WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP, layout.backendEdit, kIdBackendEdit);

      // 安装位置：装到哪儿。
      CreateChildRect(window, L"BUTTON", kTextLocationGroup, BS_GROUPBOX, layout.locationGroup, 0);
      CreateChildRect(window, L"STATIC", kTextDirectoryLabel, SS_LEFT, layout.directoryLabel,
                      kIdDirectoryLabel);
      state->directoryEdit = CreateChildRect(window, L"EDIT", state->directory.c_str(),
                                             WS_BORDER | ES_AUTOHSCROLL | WS_TABSTOP,
                                             layout.directoryEdit, kIdDirectoryEdit);
      state->browseButton = CreateChildRect(window, L"BUTTON", kTextBrowse,
                                            BS_PUSHBUTTON | WS_TABSTOP, layout.browse, kIdBrowse);
      state->programFilesCheck =
          CreateChildRect(window, L"BUTTON", kTextProgramFiles, BS_AUTOCHECKBOX | WS_TABSTOP,
                          layout.programFiles, kIdProgramFiles);

      // 安装方式：安装（带快捷方式与卸载入口）或只下载便携版。
      CreateChildRect(window, L"BUTTON", kTextModeGroup, BS_GROUPBOX, layout.modeGroup, 0);
      state->modeInstallRadio =
          CreateChildRect(window, L"BUTTON", kTextModeInstall,
                          BS_AUTORADIOBUTTON | WS_GROUP | WS_TABSTOP, layout.modeInstall,
                          kIdModeInstall);
      state->modePortableRadio =
          CreateChildRect(window, L"BUTTON", kTextModePortable, BS_AUTORADIOBUTTON | WS_TABSTOP,
                          layout.modePortable, kIdModePortable);
      state->modeHint =
          CreateChildRect(window, L"STATIC", kModeHintInstallText, SS_LEFT, layout.modeHint,
                          kIdModeHint);
      state->desktopShortcutCheck =
          CreateChildRect(window, L"BUTTON", kTextDesktopShortcut, BS_AUTOCHECKBOX | WS_TABSTOP,
                          layout.desktopShortcut, kIdDesktopShortcut);
      ::SendMessageW(state->desktopShortcutCheck, BM_SETCHECK, BST_CHECKED, 0);
      ::SendMessageW(state->portable ? state->modePortableRadio : state->modeInstallRadio,
                     BM_SETCHECK, BST_CHECKED, 0);

      state->launchCheck = CreateChildRect(window, L"BUTTON", kTextLaunch,
                                           BS_AUTOCHECKBOX | WS_TABSTOP, layout.launch, kIdLaunch);
      ::SendMessageW(state->launchCheck, BM_SETCHECK, BST_CHECKED, 0);

      state->statusLabel =
          CreateChildRect(window, L"STATIC", kStatusReadyInstall, SS_LEFT, layout.status, kIdStatus);
      state->progressBar =
          CreateChildRect(window, PROGRESS_CLASS, L"", WS_BORDER, layout.progress, kIdProgress);
      if (state->progressBar != nullptr) {
        ::SendMessageW(state->progressBar, PBM_SETRANGE32, 0, 100);
      }
      state->installButton =
          CreateChildRect(window, L"BUTTON", kTextInstallButton,
                          BS_DEFPUSHBUTTON | WS_TABSTOP, layout.install, kIdInstall);
      state->cancelButton = CreateChildRect(window, L"BUTTON", kTextCancelButton,
                                            BS_PUSHBUTTON | WS_TABSTOP, layout.cancel, kIdCancel);
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
      if (!state->updateOptions.command.empty()) {
        if (result == kExitRebootRequired) {
          ::MessageBoxW(window, L"部分文件被占用，请重启电脑完成更新。", L"魔法裁判 更新",
                        MB_OK | MB_ICONINFORMATION);
        } else if (result != kExitOk && result != kExitUpToDate) {
          ::MessageBoxW(window,
                        Format(L"更新没有完成（退出码 %d）。\n详细信息见 %s", result,
                               LogFilePath().c_str()).c_str(),
                        L"魔法裁判 更新", MB_OK | MB_ICONERROR);
        }
        ::DestroyWindow(window);
        return 0;
      }
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
        ::MessageBoxW(window, state->updateOptions.command.empty() ? L"正在安装，请等待完成。"
                                                                  : L"正在更新，请等待完成。",
                      L"魔法裁判", MB_OK | MB_ICONINFORMATION);
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

struct UninstallLayout {
  RECT heading;
  RECT list;
  RECT filesCheck;
  RECT dataCheck;
  RECT status;
  RECT start;
  RECT cancel;
  int clientWidth = 0;
  int clientHeight = 0;
};

UninstallLayout ComputeUninstallLayout(HDC dc) {
  Layout layout = BaseLayout(dc);
  int required = layout.Scale(560);
  required = std::max(required, CheckboxWidth(layout, dc, kTextRemoveData));
  required = std::max(required, layout.labelWidth + layout.labelGap + layout.Scale(240));
  layout.contentWidth = required;

  UninstallLayout result;
  const int left = layout.left();
  const int right = layout.right();
  int y = layout.margin;

  result.heading = RECT{left, y, right, y + layout.textHeight};
  y += layout.textHeight + layout.Scale(6);
  // 文件清单是只读多行框，按 10 行左右留高度，装不下的部分自己滚动。
  const int listHeight = std::max(layout.Scale(150), 8 * layout.textHeight);
  result.list = RECT{left, y, right, y + listHeight};
  y += listHeight + layout.sectionGap;

  result.filesCheck = RECT{left, y, right, y + layout.checkboxHeight};
  y += layout.checkboxHeight + layout.Scale(6);
  result.dataCheck = RECT{left, y, right, y + layout.checkboxHeight};
  y += layout.checkboxHeight + layout.sectionGap;

  // 状态留两行：卸载过程中的提示常带完整路径。
  result.status = RECT{left, y, right, y + 2 * layout.textHeight + layout.Scale(2)};
  y += (result.status.bottom - result.status.top) + layout.Scale(10);

  int buttonText = std::max(TextWidth(dc, kTextUninstallButton), TextWidth(dc, kTextCancelButton));
  const int buttonWidth = std::max(layout.Scale(100), buttonText + layout.Scale(28));
  const int buttonGap = layout.Scale(10);
  result.cancel = RECT{right - buttonWidth, y, right, y + layout.buttonHeight};
  result.start = RECT{right - 2 * buttonWidth - buttonGap, y, right - buttonWidth - buttonGap,
                      y + layout.buttonHeight};
  y += layout.buttonHeight + layout.margin;

  result.clientWidth = layout.clientWidth();
  result.clientHeight = y;
  return result;
}

struct UninstallState {
  UninstallLayout layout;
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
      const UninstallLayout& layout = state->layout;

      CreateChildRect(window, L"STATIC", kTextUninstallHeading, SS_LEFT, layout.heading,
                      kIdUninstallText);
      CreateChildRect(window, L"EDIT", create->lpszName,
                      WS_BORDER | ES_MULTILINE | ES_READONLY | WS_VSCROLL | ES_AUTOVSCROLL,
                      layout.list, kIdUninstallList);
      state->filesCheck = CreateChildRect(window, L"BUTTON", kTextRemoveFiles,
                                          BS_AUTOCHECKBOX | WS_TABSTOP, layout.filesCheck,
                                          kIdRemoveFiles);
      state->dataCheck = CreateChildRect(window, L"BUTTON", kTextRemoveData,
                                         BS_AUTOCHECKBOX | WS_TABSTOP, layout.dataCheck,
                                         kIdRemoveData);
      ::SendMessageW(state->filesCheck, BM_SETCHECK, BST_CHECKED, 0);
      ::SendMessageW(state->dataCheck, BM_SETCHECK, BST_CHECKED, 0);
      if (state->directory.empty()) {
        ::EnableWindow(state->filesCheck, FALSE);
      }
      state->statusLabel = CreateChildRect(window, L"STATIC", kTextUninstallReady, SS_LEFT,
                                           layout.status, kIdStatus);
      state->startButton = CreateChildRect(window, L"BUTTON", kTextUninstallButton,
                                           BS_DEFPUSHBUTTON | WS_TABSTOP, layout.start,
                                           kIdUninstallStart);
      state->cancelButton = CreateChildRect(window, L"BUTTON", kTextCancelButton,
                                            BS_PUSHBUTTON | WS_TABSTOP, layout.cancel, kIdCancel);
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
          ::EnableWindow(state->startButton, TRUE);
          ::EnableWindow(state->cancelButton, TRUE);
          ::EnableWindow(state->dataCheck, TRUE);
          if (!state->directory.empty()) {
            ::EnableWindow(state->filesCheck, TRUE);
          }
          ::SetWindowTextW(state->statusLabel, kTextUninstallReady);
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
  {
    // 窗口大小由内容算出来，按钮和换行后的文字都不会被切掉。
    ScreenCanvas canvas;
    state.layout = ComputeChoiceLayout(canvas.dc, subtitle);
  }
  const std::wstring title = L"魔法裁判 检测到已有安装";
  const SIZE size = WindowSizeForClient(state.layout.clientWidth, state.layout.clientHeight);
  HWND window = ::CreateWindowExW(WS_EX_DLGMODALFRAME, L"MagicJudgeUpdaterChoice", subtitle.c_str(),
                                  WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                                  CW_USEDEFAULT, CW_USEDEFAULT, size.cx, size.cy, nullptr, nullptr,
                                  ::GetModuleHandleW(nullptr), &state);
  if (window == nullptr) {
    return kInstalledChoiceQuit;
  }
  ::SetWindowTextW(window, title.c_str());
  CenterWindow(window, size.cx, size.cy);
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
  {
    ScreenCanvas canvas;
    state.layout = ComputeWizardLayout(canvas.dc);
  }
  std::wstring backend = options.from.empty() ? std::wstring(kDefaultBackend) : options.from;
  const std::wstring title = L"魔法裁判 安装向导";
  const SIZE size = WindowSizeForClient(state.layout.clientWidth, state.layout.clientHeight);
  HWND window = ::CreateWindowExW(0, L"MagicJudgeUpdaterWizard", backend.c_str(),
                                  WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                                  CW_USEDEFAULT, CW_USEDEFAULT, size.cx, size.cy, nullptr, nullptr,
                                  ::GetModuleHandleW(nullptr), &state);
  if (window == nullptr) {
    ShowErrorDialog(L"魔法裁判 安装向导", L"创建窗口失败。");
    return kExitFailure;
  }
  ::SetWindowTextW(window, title.c_str());
  CenterWindow(window, size.cx, size.cy);
  ::SetForegroundWindow(window);
  RunMessageLoop(window);
  return state.result;
}

int RunUpdateWindow(const Options& options) {
  if (!RegisterWindowClass(L"MagicJudgeUpdaterUpdate", &WizardProc)) {
    ShowErrorDialog(L"魔法裁判 更新", L"注册窗口类失败。");
    return kExitFailure;
  }
  INITCOMMONCONTROLSEX controls{};
  controls.dwSize = sizeof(controls);
  controls.dwICC = ICC_PROGRESS_CLASS;
  ::InitCommonControlsEx(&controls);
  WizardState state;
  state.updateOptions = options;
  state.result = kExitFailure;
  {
    ScreenCanvas canvas;
    const Layout layout = BaseLayout(canvas.dc);
    state.layout.status = RECT{layout.left(), layout.margin, layout.right(),
                               layout.margin + 3 * layout.textHeight};
    const int y = state.layout.status.bottom + layout.sectionGap;
    state.layout.progress = RECT{layout.left(), y, layout.right(), y + layout.Scale(20)};
    state.layout.clientWidth = layout.clientWidth();
    state.layout.clientHeight = state.layout.progress.bottom + layout.margin;
  }
  const SIZE size = WindowSizeForClient(state.layout.clientWidth, state.layout.clientHeight);
  HWND window = ::CreateWindowExW(0, L"MagicJudgeUpdaterUpdate", L"魔法裁判 更新",
                                  WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                                  CW_USEDEFAULT, CW_USEDEFAULT, size.cx, size.cy, nullptr, nullptr,
                                  ::GetModuleHandleW(nullptr), &state);
  if (window == nullptr) {
    ShowErrorDialog(L"魔法裁判 更新", L"创建窗口失败。");
    return kExitFailure;
  }
  CenterWindow(window, size.cx, size.cy);
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
  {
    ScreenCanvas canvas;
    state.layout = ComputeUninstallLayout(canvas.dc);
  }
  const std::wstring title = L"魔法裁判 卸载";
  const SIZE size = WindowSizeForClient(state.layout.clientWidth, state.layout.clientHeight);
  HWND window = ::CreateWindowExW(0, L"MagicJudgeUpdaterUninstall", summary.c_str(),
                                  WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
                                  CW_USEDEFAULT, CW_USEDEFAULT, size.cx, size.cy, nullptr, nullptr,
                                  ::GetModuleHandleW(nullptr), &state);
  if (window == nullptr) {
    ShowErrorDialog(L"魔法裁判 卸载", L"创建窗口失败。");
    return kExitFailure;
  }
  ::SetWindowTextW(window, title.c_str());
  CenterWindow(window, size.cx, size.cy);
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
