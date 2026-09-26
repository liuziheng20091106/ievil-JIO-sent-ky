cmake_minimum_required(VERSION 3.14)
project(updater LANGUAGES CXX)

# Updater：安装向导 / 应用内更新 / 证书与计划任务准备 / 卸载。
# 只用 Windows API + CRT，产物要与 seven_double_client.exe 放在同一个目录
# （package-release.cmd 整目录压缩时自动带上它）。
add_executable(Updater WIN32
  "archive.cpp"
  "common.cpp"
  "gui.cpp"
  "http.cpp"
  "install.cpp"
  "job.cpp"
  "json.cpp"
  "main.cpp"
  "system.cpp"
  "update.cpp"
  "updater.exe.manifest"
)

apply_standard_settings(Updater)

target_compile_definitions(Updater PRIVATE "NOMINMAX")
target_compile_definitions(Updater PRIVATE "_CRT_SECURE_NO_WARNINGS")
target_compile_definitions(Updater PRIVATE "WIN32_LEAN_AND_MEAN")
target_compile_definitions(Updater PRIVATE "_WIN32_WINNT=0x0A00")
target_compile_definitions(Updater PRIVATE "WINVER=0x0A00")

target_include_directories(Updater PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
target_include_directories(Updater PRIVATE "${CMAKE_SOURCE_DIR}")

target_link_libraries(Updater PRIVATE
  "advapi32.lib"
  "bcrypt.lib"
  "comctl32.lib"
  "crypt32.lib"
  "ole32.lib"
  "shell32.lib"
  "shlwapi.lib"
  "user32.lib"
  "winhttp.lib"
)

# 直接落在 runner/Release 里，省得依赖 INSTALL 步骤。
set_target_properties(Updater PROPERTIES
  OUTPUT_NAME "Updater"
  RUNTIME_OUTPUT_DIRECTORY "$<TARGET_FILE_DIR:${BINARY_NAME}>"
)
