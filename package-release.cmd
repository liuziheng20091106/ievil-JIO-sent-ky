@echo off
rem 每次编译 Windows 发行后调用：把 Release 目录重新打成 zip，
rem 再把 zip 与安卓发行 APK 一起覆盖到局域网分发目录。
setlocal
set "ROOT=%~dp0"
set "RELEASE=%ROOT%client\build\windows\x64\runner\Release"
set "ZIP=%RELEASE%\魔法裁判Windows.zip"
set "APK=%ROOT%client\build\app\outputs\flutter-apk\app-release.apk"
set "DIST=\\192.168.0.114\烟台一中\云控\信息技术"

if not exist "%RELEASE%\seven_double_client.exe" (
    echo 缺少 Windows 发行产物，请先 flutter build windows --release
    exit /b 1
)
if not exist "%APK%" (
    echo 缺少安卓发行 APK，请先 flutter build apk --release --target-platform android-arm64
    exit /b 1
)

if exist "%ZIP%" del /f "%ZIP%"
powershell.exe -NoProfile -Command "Compress-Archive -Path '%RELEASE%\*' -DestinationPath '%ZIP%' -CompressionLevel Optimal" || exit /b 1

copy /y "%ZIP%" "%DIST%\" >nul || exit /b 1
copy /y "%APK%" "%DIST%\" >nul || exit /b 1
echo 已发布到 %DIST%
