#pragma once

// %LOCALAPPDATA%\MagicJudge\job.json：--update-app 写给计划任务里 --task-entry 的活。

#include <string>

#include "common.h"

namespace upd {

struct UpdateJob {
  std::wstring packageUrl;
  std::wstring sha256;
  long long size = -1;
  std::wstring target;
  std::wstring restart;
  std::wstring version;
  DWORD waitPid = 0;
  bool silent = false;
};

bool WriteUpdateJob(const UpdateJob& job, std::wstring* error);
bool ReadUpdateJob(UpdateJob* job, std::wstring* error);
bool DeleteUpdateJob();

}  // namespace upd
