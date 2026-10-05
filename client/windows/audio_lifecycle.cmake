include_guard(GLOBAL)

# audioplayers_windows 4.4.1 returns from source methods before detached workers
# finish. Patch a build-directory copy; never mutate the Pub cache or generated
# plugin registration. Each replacement must match exactly once.
set(audio_target audioplayers_windows_plugin)
get_target_property(audio_source_dir ${audio_target} SOURCE_DIR)
file(READ "${audio_source_dir}/../pubspec.yaml" audio_pubspec)
if(NOT audio_pubspec MATCHES "\nversion: 4\\.4\\.1[\r\n]")
  message(FATAL_ERROR "The audio lifecycle patch requires audioplayers_windows 4.4.1")
endif()
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
  "${audio_source_dir}/../pubspec.yaml"
  "${audio_source_dir}/audioplayers_windows_plugin.cpp"
  "${audio_source_dir}/MediaEngineWrapper.cpp"
  "${audio_source_dir}/MediaEngineWrapper.h")

function(audio_replace variable before after)
  set(text "${${variable}}")
  string(FIND "${text}" "${before}" first)
  if(first EQUAL -1)
    message(FATAL_ERROR "Missing expected audioplayers_windows lifecycle patch pattern: ${before}")
  endif()
  string(LENGTH "${before}" length)
  math(EXPR next "${first} + ${length}")
  string(SUBSTRING "${text}" ${next} -1 remainder)
  string(FIND "${remainder}" "${before}" duplicate)
  if(NOT duplicate EQUAL -1)
    message(FATAL_ERROR "Ambiguous audioplayers_windows lifecycle patch pattern: ${before}")
  endif()
  string(REPLACE "${before}" "${after}" text "${text}")
  set(${variable} "${text}" PARENT_SCOPE)
endfunction()

file(READ "${audio_source_dir}/audioplayers_windows_plugin.cpp" audio_plugin)
audio_replace(audio_plugin
  "#include <iostream>"
  "#include <iostream>\n#include <atomic>\n#include <chrono>\n#include <mutex>\n#include <vector>")
audio_replace(audio_plugin
  "class AudioplayersWindowsPlugin : public Plugin {"
  [=[struct SourceResponses {
  HWND window = nullptr;
  UINT message = RegisterWindowMessageW(L"SevenDouble.AudioSourceComplete");
  std::mutex mutex;
  std::vector<std::function<void()>> tasks;

  void Dispatch(std::function<void()> task) {
    {
      std::lock_guard<std::mutex> lock(mutex);
      tasks.push_back(std::move(task));
    }
    // Plugins register before SetChildContent. Resolve the attached root now,
    // rather than caching the then-unparented Flutter view as the root.
    PostMessage(GetAncestor(window, GA_ROOT), message, 0, 0);
  }

  void Complete(std::unique_ptr<MethodResult<EncodableValue>> result) {
    auto response = std::shared_ptr<MethodResult<EncodableValue>>(std::move(result));
    Dispatch([response]() { response->Success(); });
  }

  void Reply() {
    std::vector<std::function<void()>> ready;
    {
      std::lock_guard<std::mutex> lock(mutex);
      ready.swap(tasks);
    }
    for (auto& task : ready) task();
  }
};

class AudioplayersWindowsPlugin : public Plugin {]=])
audio_replace(audio_plugin
  "std::map<std::string, std::unique_ptr<AudioPlayer>> audioPlayers;"
  [=[std::map<std::string, std::shared_ptr<AudioPlayer>> audioPlayers;
  std::vector<std::future<void>> sourceLoads;

  std::map<std::string, std::shared_ptr<std::atomic<bool>>> sourceActive;
  std::shared_ptr<SourceResponses> responses = std::make_shared<SourceResponses>();
  PluginRegistrarWindows* registrar = nullptr;
  int responseDelegate = -1;

  bool SourceLoading(const std::string& playerId) {
    const auto load = sourceActive.find(playerId);
    return load != sourceActive.end() && load->second->load();
  }]=])
audio_replace(audio_plugin
  "AudioPlayer* GetPlayer(std::string playerId);"
  "std::shared_ptr<AudioPlayer> GetPlayer(std::string playerId);")
audio_replace(audio_plugin
  "plugin->binaryMessenger = registrar->messenger();"
  [=[plugin->binaryMessenger = registrar->messenger();
  plugin->registrar = registrar;
  auto responses = plugin->responses;
  if (registrar->GetView()) {
    responses->window = registrar->GetView()->GetNativeWindow();
  }
  plugin->responseDelegate = registrar->RegisterTopLevelWindowProcDelegate(
      [responses](HWND, UINT message, WPARAM, LPARAM) -> std::optional<LRESULT> {
        if (message != responses->message) return std::nullopt;
        responses->Reply();
        return 0;
      });]=])
audio_replace(audio_plugin
  "auto handler = std::make_unique<EventStreamHandler<EncodableValue>>();"
  [=[auto globalMessages = plugin->responses;
  auto handler = std::make_unique<EventStreamHandler<>>(
      [globalMessages](std::function<void()> task) {
        globalMessages->Dispatch(std::move(task));
      });]=])
audio_replace(audio_plugin
  "auto eventHandler = std::make_unique<EventStreamHandler<EncodableValue>>();"
  [=[auto messages = responses;
  auto eventHandler = std::make_unique<EventStreamHandler<>>(
      [messages](std::function<void()> task) {
        messages->Dispatch(std::move(task));
      });]=])
audio_replace(audio_plugin
  "AudioplayersWindowsPlugin::~AudioplayersWindowsPlugin() {}"
  [=[AudioplayersWindowsPlugin::~AudioplayersWindowsPlugin() {
  // Only process teardown waits for outstanding workers. Normal controls and
  // Dart source completion use the platform message, without blocking the UI.
  sourceLoads.clear();
  for (const auto& entry : audioPlayers) entry.second->Dispose();
  registrar->UnregisterTopLevelWindowProcDelegate(responseDelegate);
}]=])
audio_replace(audio_plugin
  "if (method_call.method_name().compare(\"init\") == 0) {"
  [=[if (method_call.method_name().compare("init") == 0) {
    for (const auto& entry : sourceActive) {
      if (entry.second->load()) {
        result->Error("WindowsAudioError", "Audio source is still loading");
        return;
      }
    }]=])
audio_replace(audio_plugin
  "std::thread(&AudioPlayer::SetSourceUrl, player, url).detach();"
  [=[if (SourceLoading(playerId) || !responses->window || !responses->message) {
      result->Error("WindowsAudioError", "Audio source completion is unavailable");
      return;
    }
    auto active = std::make_shared<std::atomic<bool>>(true);
    sourceActive[playerId] = active;
    auto completion = responses;
    sourceLoads.push_back(std::async(std::launch::async,
        [player, url, active, completion, result = std::move(result)]() mutable {
          player->SetSourceUrl(url);
          active->store(false);
          completion->Complete(std::move(result));
        }));
    return;]=])
audio_replace(audio_plugin
  "std::thread(&AudioPlayer::SetSourceBytes, player, data).detach();"
  [=[if (SourceLoading(playerId) || !responses->window || !responses->message) {
      result->Error("WindowsAudioError", "Audio source completion is unavailable");
      return;
    }
    auto active = std::make_shared<std::atomic<bool>>(true);
    sourceActive[playerId] = active;
    auto completion = responses;
    sourceLoads.push_back(std::async(std::launch::async,
        [player, data = std::move(data), active, completion,
         result = std::move(result)]() mutable {
          player->SetSourceBytes(data);
          active->store(false);
          completion->Complete(std::move(result));
        }));
    return;]=])
audio_replace(audio_plugin
  "auto player = GetPlayer(playerId);"
  [=[// Reap finished worker futures only; never join an active source on UI.
  for (auto load = sourceLoads.begin(); load != sourceLoads.end();) {
    if (load->wait_for(std::chrono::seconds(0)) == std::future_status::ready) {
      load->get();
      load = sourceLoads.erase(load);
    } else {
      ++load;
    }
  }
  const auto& method = method_call.method_name();
  if (SourceLoading(playerId) &&
      (method == "stop" || method == "release" || method == "dispose")) {
    result->Error("WindowsAudioError", "Audio source is still loading");
    return;
  }
  auto player = GetPlayer(playerId);]=])
audio_replace(audio_plugin
  "audioPlayers.erase(playerId);"
  "audioPlayers.erase(playerId);\n    sourceActive.erase(playerId);")
audio_replace(audio_plugin
  "std::make_unique<AudioPlayer>(playerId, methods.get(), eventHandlerPtr)"
  "std::make_shared<AudioPlayer>(playerId, methods.get(), eventHandlerPtr)")
audio_replace(audio_plugin
  "AudioPlayer* AudioplayersWindowsPlugin::GetPlayer(std::string playerId)"
  "std::shared_ptr<AudioPlayer> AudioplayersWindowsPlugin::GetPlayer(std::string playerId)")
audio_replace(audio_plugin
  "return searchPlayer->second.get();"
  "return searchPlayer->second;")

# Queued Media Foundation callbacks also capture the player. Detach under the
# helper's callback lock before Shutdown, outside the wrapper lock to preserve
# callback -> wrapper lock order. Player and channels still live at this point.
file(READ "${audio_source_dir}/MediaEngineWrapper.h" audio_header)
audio_replace(audio_header
  "winrt::com_ptr<IMFMediaEngineNotify> m_callbackHelper;"
  "winrt::com_ptr<IMFMediaEngineNotify> m_callbackHelper;\n  std::function<void()> m_detachCallback;")
file(READ "${audio_source_dir}/MediaEngineWrapper.cpp" audio_wrapper)
audio_replace(audio_wrapper
  "m_callbackHelper = winrt::make<MediaEngineCallbackHelper>("
  "auto callbackHelper = winrt::make_self<MediaEngineCallbackHelper>(")
audio_replace(audio_wrapper
  "[&]() { this->OnPlaybackEnded(); }, [&]() { this->OnSeekCompleted(); });"
  [=[[&]() { this->OnPlaybackEnded(); }, [&]() { this->OnSeekCompleted(); });
  m_callbackHelper = callbackHelper.as<IMFMediaEngineNotify>();
  m_detachCallback = [callbackHelper]() { callbackHelper->DetachParent(); };]=])
audio_replace(audio_wrapper
  "void MediaEngineWrapper::Shutdown() {\n  RunSyncInMTA"
  [=[void MediaEngineWrapper::Shutdown() {
  if (m_detachCallback) {
    m_detachCallback();
    m_detachCallback = nullptr;
  }
  RunSyncInMTA]=])

set(audio_overlay "${CMAKE_CURRENT_BINARY_DIR}/audio_lifecycle")
file(MAKE_DIRECTORY "${audio_overlay}")
file(COPY "${audio_source_dir}/" DESTINATION "${audio_overlay}")
file(WRITE "${audio_overlay}/audioplayers_windows_plugin.cpp" "${audio_plugin}")
file(WRITE "${audio_overlay}/MediaEngineWrapper.h" "${audio_header}")
file(WRITE "${audio_overlay}/MediaEngineWrapper.cpp" "${audio_wrapper}")
configure_file("${CMAKE_CURRENT_LIST_DIR}/audio_event_stream_handler.h"
  "${audio_overlay}/event_stream_handler.h" COPYONLY)
get_target_property(audio_sources ${audio_target} SOURCES)
set(audio_patched_sources)
foreach(audio_source IN LISTS audio_sources)
  get_filename_component(audio_name "${audio_source}" NAME)
  if(NOT EXISTS "${audio_overlay}/${audio_name}")
    message(FATAL_ERROR "Unexpected audioplayers_windows target source: ${audio_source}")
  endif()
  list(APPEND audio_patched_sources "${audio_overlay}/${audio_name}")
endforeach()
set_property(TARGET ${audio_target} PROPERTY SOURCES "${audio_patched_sources}")
target_include_directories(${audio_target} PRIVATE "${audio_overlay}")
