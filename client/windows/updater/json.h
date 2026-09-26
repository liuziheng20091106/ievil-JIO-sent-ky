#pragma once

// 极简 JSON：只够 Updater 自己用（job.json 的扁平对象 + /api/health 的嵌套对象）。
// 不引第三方库；解析失败一律返回 false，不抛异常。

#include <string>
#include <utility>
#include <vector>

namespace upd {

struct JsonValue {
  enum class Kind { Null, Bool, Number, String, Object, Array };

  Kind kind = Kind::Null;
  bool boolean = false;
  long long integer = 0;
  double decimal = 0.0;
  std::wstring text;
  std::vector<std::pair<std::wstring, JsonValue>> members;
  std::vector<JsonValue> items;

  bool IsNull() const { return kind == Kind::Null; }
  bool IsObject() const { return kind == Kind::Object; }
  // 取成员；不存在返回 nullptr。key 按区分大小写比较。
  const JsonValue* Member(const std::wstring& key) const;
  // 取成员文本；非字符串或不存在时返回 fallback。
  std::wstring MemberText(const std::wstring& key, const std::wstring& fallback = std::wstring()) const;
  // 取成员整数；非数字或不存在时返回 fallback。
  long long MemberNumber(const std::wstring& key, long long fallback = 0) const;
};

// 解析 UTF-8 JSON 文本；失败返回 false。
bool JsonParse(const std::string& utf8, JsonValue* value);

// 按 "a.b.c" 的路径逐层下降取字符串。任一层缺失或类型不符返回 false。
bool JsonLookupText(const std::string& utf8, const std::wstring& path, std::wstring* text);

// 构造一个扁平对象（只放字符串和整数）。
class JsonWriter {
 public:
  void SetText(const std::wstring& key, const std::wstring& value);
  void SetNumber(const std::wstring& key, long long value);
  std::string ToUtf8() const;

 private:
  struct Field {
    std::wstring key;
    std::wstring text;
    long long number = 0;
    bool isText = true;
  };
  std::vector<Field> fields_;
};

}  // namespace upd
