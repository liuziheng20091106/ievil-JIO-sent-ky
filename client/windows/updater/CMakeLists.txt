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

# 更新器有 10 个互不依赖的翻译单元，每个都要单独解析一遍 windows.h：实测
# 2.7-6s/个，且与源码行数几乎无关（45 行的 job.cpp 也要 2.8s）。MSBuild 默认
# 串行编译（不带 /MP），整个目标约 40s；开 /MP 让 cl.exe 并行编译这些文件后
# 约 14s（本机 8 核，瓶颈落在最大的 gui.cpp 与链接上）。
# 只加在 Updater 上：apply_standard_settings 是 Flutter 插件共用的，别动它。
target_compile_options(Updater PRIVATE "/MP")

target_compile_definitions(Updater PRIVATE "NOMINMAX")
target_compile_definitions(Updater PRIVATE "_CRT_SECURE_NO_WARNINGS")
target_compile_definitions(Updater PRIVATE "WIN32_LEAN_AND_MEAN")
target_compile_definitions(Updater PRIVATE "_WIN32_WINNT=0x0A00")
target_compile_definitions(Updater PRIVATE "WINVER=0x0A00")

target_include_directories(Updater PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
target_include_directories(Updater PRIVATE "${CMAKE_SOURCE_DIR}")

# 版本号只在一处维护：从 client/pubspec.yaml 的版本名取（与客户端内置版本号同源），
# 免得发版时还要记得手改 version.h。
set(UPDATER_VERSION "0.0.0")
if(EXISTS "${CMAKE_SOURCE_DIR}/../pubspec.yaml")
  file(READ "${CMAKE_SOURCE_DIR}/../pubspec.yaml" UPDATER_PUBSPEC)
  string(REGEX MATCH "version:[ \t]*([0-9]+\\.[0-9]+\\.[0-9]+)" _updater_version "${UPDATER_PUBSPEC}")
  if(CMAKE_MATCH_1)
    set(UPDATER_VERSION "${CMAKE_MATCH_1}")
  endif()
endif()
message(STATUS "Updater 版本 ${UPDATER_VERSION}（来自 client/pubspec.yaml）")
target_compile_definitions(Updater PRIVATE "UPDATER_VERSION_STRING=L\"${UPDATER_VERSION}\"")

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
