#include "flutter_window.h"

#include <optional>
#include <shobjidl.h>
#include <flutter/method_channel.h>
#include <flutter/standard_method_codec.h>
#include <fstream>
#include <wrl/client.h>

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

  history_export_channel_ =
      std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
          flutter_controller_->engine()->messenger(), "history_export",
          &flutter::StandardMethodCodec::GetInstance());
  history_export_channel_->SetMethodCallHandler(
      [this](const auto& call, auto result) {
        if (call.method_name() != "save") {
          result->NotImplemented();
          return;
        }
        if (history_export_busy_) {
          result->Error("busy", "正在保存对局记录");
          return;
        }
        const auto* arguments = std::get_if<flutter::EncodableMap>(call.arguments());
        const std::string* filename = nullptr;
        const std::vector<uint8_t>* bytes = nullptr;
        if (arguments) {
          auto name = arguments->find(flutter::EncodableValue("filename"));
          auto content = arguments->find(flutter::EncodableValue("bytes"));
          if (name != arguments->end()) filename = std::get_if<std::string>(&name->second);
          if (content != arguments->end()) bytes = std::get_if<std::vector<uint8_t>>(&content->second);
        }
        if (!filename || filename->empty() || !bytes ||
            filename->find_first_of("/\\\0", 0, 3) != std::string::npos) {
          result->Error("arguments", "保存参数无效");
          return;
        }
        const int name_length = MultiByteToWideChar(
            CP_UTF8, MB_ERR_INVALID_CHARS, filename->c_str(), -1, nullptr, 0);
        if (name_length == 0) {
          result->Error("arguments", "文件名不是有效 UTF-8");
          return;
        }
        std::wstring name(name_length, L'\0');
        MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS,
                            filename->c_str(), -1, name.data(), name_length);
        name.resize(name_length - 1);
        history_export_busy_ = true;
        struct BusyReset {
          bool& busy;
          ~BusyReset() { busy = false; }
        } reset{history_export_busy_};
        Microsoft::WRL::ComPtr<IFileSaveDialog> dialog;
        HRESULT status = CoCreateInstance(CLSID_FileSaveDialog, nullptr,
            CLSCTX_INPROC_SERVER, IID_PPV_ARGS(dialog.GetAddressOf()));
        const COMDLG_FILTERSPEC filters[] = {{L"文本文件", L"*.txt"}};
        FILEOPENDIALOGOPTIONS options = 0;
        if (SUCCEEDED(status)) status = dialog->GetOptions(&options);
        if (SUCCEEDED(status)) status = dialog->SetOptions(
            options | FOS_FORCEFILESYSTEM | FOS_OVERWRITEPROMPT | FOS_PATHMUSTEXIST);
        if (SUCCEEDED(status)) status = dialog->SetFileTypes(1, filters);
        if (SUCCEEDED(status)) status = dialog->SetDefaultExtension(L"txt");
        if (SUCCEEDED(status)) status = dialog->SetFileName(name.c_str());
        if (SUCCEEDED(status)) status = dialog->Show(GetHandle());
        if (status == HRESULT_FROM_WIN32(ERROR_CANCELLED)) {
          result->Success();
          return;
        }
        Microsoft::WRL::ComPtr<IShellItem> item;
        if (SUCCEEDED(status)) status = dialog->GetResult(item.GetAddressOf());
        PWSTR selected_path = nullptr;
        if (SUCCEEDED(status)) status = item->GetDisplayName(SIGDN_FILESYSPATH, &selected_path);
        if (FAILED(status)) {
          CoTaskMemFree(selected_path);
          result->Error("save", "无法打开保存位置", flutter::EncodableValue(static_cast<int64_t>(status)));
          return;
        }
        const std::wstring path(selected_path);
        CoTaskMemFree(selected_path);
        const int path_length = WideCharToMultiByte(
            CP_UTF8, WC_ERR_INVALID_CHARS, path.c_str(), -1, nullptr, 0, nullptr, nullptr);
        if (path_length == 0) {
          result->Error("save", "无法读取保存路径");
          return;
        }
        std::string saved_path(path_length, '\0');
        WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, path.c_str(), -1,
                            saved_path.data(), path_length, nullptr, nullptr);
        saved_path.resize(path_length - 1);
        HANDLE file = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr,
                                  CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (file == INVALID_HANDLE_VALUE) {
          result->Error("save", "无法写入对局记录", flutter::EncodableValue(static_cast<int64_t>(GetLastError())));
          return;
        }
        DWORD failure = ERROR_SUCCESS;
        size_t offset = 0;
        while (offset < bytes->size()) {
          const DWORD count = static_cast<DWORD>(
              (bytes->size() - offset) > 1024 * 1024 ? 1024 * 1024 : bytes->size() - offset);
          DWORD written = 0;
          if (!WriteFile(file, bytes->data() + offset, count, &written, nullptr)) {
            failure = GetLastError();
            break;
          }
          if (written == 0) {
            failure = ERROR_WRITE_FAULT;
            break;
          }
          offset += written;
        }
        if (failure == ERROR_SUCCESS && !FlushFileBuffers(file)) failure = GetLastError();
        if (!CloseHandle(file) && failure == ERROR_SUCCESS) failure = GetLastError();
        if (failure != ERROR_SUCCESS) {
          result->Error("save", "对局记录写入失败", flutter::EncodableValue(static_cast<int64_t>(failure)));
          return;
        }
        result->Success(flutter::EncodableValue(std::move(saved_path)));
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
  history_export_channel_ = nullptr;
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
