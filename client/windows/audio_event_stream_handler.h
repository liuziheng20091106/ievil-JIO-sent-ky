#pragma once

#include <flutter/encodable_value.h>
#include <flutter/event_channel.h>

#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <utility>

using namespace flutter;

// Media Foundation callbacks can arrive on workers. Dispatch every sink access
// to the platform queue; queued events become inert when the stream cancels.
template <typename T = EncodableValue>
class EventStreamHandler : public StreamHandler<T> {
 public:
  using Dispatch = std::function<void(std::function<void()>)>;

  explicit EventStreamHandler(Dispatch dispatch)
      : m_dispatch(std::move(dispatch)) {}

  void Success(std::unique_ptr<T> value) {
    const auto sink = CurrentSink();
    auto data = std::shared_ptr<T>(std::move(value));
    m_dispatch([sink, data]() {
      if (auto target = sink.lock()) target->Success(*data);
    });
  }

  void Error(const std::string& code, const std::string& message,
             const T* details = nullptr) {
    const auto sink = CurrentSink();
    const std::optional<T> data = details ? std::optional<T>(*details) : std::nullopt;
    m_dispatch([sink, code, message, data]() {
      if (auto target = sink.lock()) {
        if (data) target->Error(code, message, *data);
        else target->Error(code, message);
      }
    });
  }

 protected:
  std::unique_ptr<StreamHandlerError<T>> OnListenInternal(
      const T*, std::unique_ptr<EventSink<T>>&& events) override {
    std::lock_guard<std::mutex> lock(m_mutex);
    m_sink = std::move(events);
    return nullptr;
  }

  std::unique_ptr<StreamHandlerError<T>> OnCancelInternal(const T*) override {
    std::lock_guard<std::mutex> lock(m_mutex);
    m_sink.reset();
    return nullptr;
  }

 private:
  std::weak_ptr<EventSink<T>> CurrentSink() {
    std::lock_guard<std::mutex> lock(m_mutex);
    return m_sink;
  }

  Dispatch m_dispatch;
  std::mutex m_mutex;
  std::shared_ptr<EventSink<T>> m_sink;
};
