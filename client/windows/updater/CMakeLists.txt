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

# 发行版本唯一取自 Dart 常量；改版本后重新配置，避免增量构建沿用旧宏。
set(UPDATER_VERSION_FILE "${CMAKE_CURRENT_SOURCE_DIR}/../../lib/src/client_version.dart")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${UPDATER_VERSION_FILE}")
file(STRINGS "${UPDATER_VERSION_FILE}" UPDATER_VERSION_LINE REGEX "^[ \t]*const[ \t]+kClientVersion[ \t]*=")
# file(STRINGS) 返回列表；JOIN 解开 Dart 语句末尾分号的列表转义。
list(JOIN UPDATER_VERSION_LINE "\n" UPDATER_VERSION_LINE)
if(NOT UPDATER_VERSION_LINE MATCHES "^[ \t]*const[ \t]+kClientVersion[ \t]*=[ \t]*('([0-9]+\\.[0-9]+\\.[0-9]+)'|\"([0-9]+\\.[0-9]+\\.[0-9]+)\")[ \t]*;[ \t]*$")
  message(FATAL_ERROR "client/lib/src/client_version.dart 缺少合法的三段 kClientVersion 发行版本")
endif()
set(UPDATER_VERSION "${CMAKE_MATCH_2}${CMAKE_MATCH_3}")

# 版本宏只传给真正使用版本号的 4 个源文件；挂在 target 上会让整个更新器失去编译缓存。
set_source_files_properties(
  "gui.cpp" "install.cpp" "main.cpp" "update.cpp"
  PROPERTIES COMPILE_DEFINITIONS "UPDATER_VERSION_STRING=L\"${UPDATER_VERSION}\"")
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
