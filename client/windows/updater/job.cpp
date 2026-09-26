#include "job.h"

#include "json.h"

namespace upd {

bool WriteUpdateJob(const UpdateJob& job, std::wstring* error) {
  JsonWriter writer;
  writer.SetText(L"package_url", job.packageUrl);
  writer.SetText(L"sha256", job.sha256);
  writer.SetNumber(L"size", job.size);
  writer.SetText(L"target", job.target);
  writer.SetText(L"restart", job.restart);
  writer.SetText(L"version", job.version);
  writer.SetNumber(L"wait_pid", static_cast<long long>(job.waitPid));
  writer.SetNumber(L"silent", job.silent ? 1 : 0);
  return WriteTextFileUtf8(JobFilePath(), writer.ToUtf8(), error);
}

bool ReadUpdateJob(UpdateJob* job, std::wstring* error) {
  std::string text;
  if (!ReadTextFileUtf8(JobFilePath(), &text, error)) {
    return false;
  }
  JsonValue root;
  if (!JsonParse(text, &root) || !root.IsObject()) {
    *error = Format(L"job.json 解析失败：%s", JobFilePath().c_str());
    return false;
  }
  *job = UpdateJob();
  job->packageUrl = root.MemberText(L"package_url");
  job->sha256 = root.MemberText(L"sha256");
  job->target = root.MemberText(L"target");
  job->restart = root.MemberText(L"restart");
  job->version = root.MemberText(L"version");
  job->size = root.MemberNumber(L"size", -1);
  job->waitPid = static_cast<DWORD>(root.MemberNumber(L"wait_pid", 0));
  job->silent = root.MemberNumber(L"silent", 0) != 0;
  if (job->packageUrl.empty() || job->target.empty()) {
    *error = L"job.json 缺少 package_url 或 target";
    return false;
  }
  return true;
}

bool DeleteUpdateJob() {
  std::wstring ignored;
  return DeleteFileIfExists(JobFilePath(), &ignored);
}

}  // namespace upd
