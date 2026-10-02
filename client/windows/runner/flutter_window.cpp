#include "flutter_window.h"

#include <optional>
#include <shobjidl.h>
#include <flutter/method_channel.h>
#include <flutter/standard_method_codec.h>
#include <fstream>

#include "flutter/generated_plugin_registrant.h"

FlutterWindow::FlutterWindow(const flutter::DartProject& project)
    : project_(project) {}

FlutterWindow::~FlutterWindow() {}

bool FlutterWindow::OnCreate() {
  if (!Win32Window::OnCreate()) {
    return false;
  }

  RECT frame = GetClientArea();

  // The size here must match the window dimensions to avoid unnecessary surface
  // creation / destruction in the startup path.
  flutter_controller_ = std::make_unique<flutter::FlutterViewController>(
      frame.right - frame.left, frame.bottom - frame.top, project_);
  // Ensure that basic setup of the controller was successful.
  if (!flutter_controller_->engine() || !flutter_controller_->view()) {
    return false;
  }
  RegisterPlugins(flutter_controller_->engine());
  SetChildContent(flutter_controller_->view()->GetNativeWindow());

  image_channel_ = std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
      flutter_controller_->engine()->messenger(), "chat_image",
      &flutter::StandardMethodCodec::GetInstance());
  image_channel_->SetMethodCallHandler(
      [this](const auto& call, auto result) {
        if (call.method_name() != "pick") {
          result->NotImplemented();
          return;
        }
        IFileOpenDialog* dialog = nullptr;
        HRESULT status = CoCreateInstance(CLSID_FileOpenDialog, nullptr,
            CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&dialog));
        if (FAILED(status)) {
          result->Error("picker", "无法打开图片选择器");
          return;
        }
        const COMDLG_FILTERSPEC filters[] = {{L"图片", L"*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp"}};
        dialog->SetFileTypes(1, filters);
        status = dialog->Show(GetHandle());
        IShellItem* item = nullptr;
        if (SUCCEEDED(status)) status = dialog->GetResult(&item);
        dialog->Release();
        if (status == HRESULT_FROM_WIN32(ERROR_CANCELLED)) {
          result->Success();
          return;
        }
        if (FAILED(status)) {
          result->Error("picker", "无法读取所选图片");
          return;
        }
        PWSTR path = nullptr;
        status = item->GetDisplayName(SIGDN_FILESYSPATH, &path);
        item->Release();
        if (FAILED(status)) {
          result->Error("picker", "无法读取所选图片");
          return;
        }
        std::ifstream file(path, std::ios::binary | std::ios::ate);
        CoTaskMemFree(path);
        const auto size = file.tellg();
        if (!file || size <= 0 || size > 20 * 1024 * 1024) {
          result->Error("image", "请选择20MB以内的图片");
          return;
        }
        std::vector<uint8_t> bytes(static_cast<size_t>(size));
        file.seekg(0);
        if (!file.read(reinterpret_cast<char*>(bytes.data()), size)) {
          result->Error("image", "无法读取所选图片");
          return;
        }
        result->Success(flutter::EncodableValue(std::move(bytes)));
      });

  flutter_controller_->engine()->SetNextFrameCallback([&]() {
    this->Show();
  });

  // Flutter can complete the first frame before the "show window" callback is
  // registered. The following call ensures a frame is pending to ensure the
  // window is shown. It is a no-op if the first frame hasn't completed yet.
  flutter_controller_->ForceRedraw();

  return true;
}

void FlutterWindow::OnDestroy() {
  image_channel_ = nullptr;
  if (flutter_controller_) {
    flutter_controller_ = nullptr;
  }

  Win32Window::OnDestroy();
}

LRESULT
FlutterWindow::MessageHandler(HWND hwnd, UINT const message,
                              WPARAM const wparam,
                              LPARAM const lparam) noexcept {
  // Give Flutter, including plugins, an opportunity to handle window messages.
  if (flutter_controller_) {
    std::optional<LRESULT> result =
        flutter_controller_->HandleTopLevelWindowProc(hwnd, message, wparam,
                                                      lparam);
    if (result) {
      return *result;
    }
  }

  switch (message) {
    case WM_FONTCHANGE:
      flutter_controller_->engine()->ReloadSystemFonts();
      break;
  }

  return Win32Window::MessageHandler(hwnd, message, wparam, lparam);
}
