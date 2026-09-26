#include "json.h"

#include <cstring>

#include "common.h"

namespace upd {
namespace {

constexpr int kMaxDepth = 32;

class Parser {
 public:
  explicit Parser(const std::string& text) : text_(text) {}

  bool Parse(JsonValue* value) {
    SkipSpace();
    if (!ParseValue(value, 0)) {
      return false;
    }
    SkipSpace();
    return index_ == text_.size();
  }

 private:
  void SkipSpace() {
    while (index_ < text_.size()) {
      const char character = text_[index_];
      if (character == ' ' || character == '\t' || character == '\r' || character == '\n') {
        ++index_;
        continue;
      }
      break;
    }
  }

  bool Literal(const char* word) {
    const size_t length = ::strlen(word);
    if (index_ + length > text_.size() || text_.compare(index_, length, word) != 0) {
      return false;
    }
    index_ += length;
    return true;
  }

  bool ParseValue(JsonValue* value, int depth) {
    if (depth > kMaxDepth) {
      return false;
    }
    SkipSpace();
    if (index_ >= text_.size()) {
      return false;
    }
    const char character = text_[index_];
    if (character == '{') {
      return ParseObject(value, depth);
    }
    if (character == '[') {
      return ParseArray(value, depth);
    }
    if (character == '"') {
      value->kind = JsonValue::Kind::String;
      return ParseString(&value->text);
    }
    if (Literal("true")) {
      value->kind = JsonValue::Kind::Bool;
      value->boolean = true;
      return true;
    }
    if (Literal("false")) {
      value->kind = JsonValue::Kind::Bool;
      value->boolean = false;
      return true;
    }
    if (Literal("null")) {
      value->kind = JsonValue::Kind::Null;
      return true;
    }
    return ParseNumber(value);
  }

  bool ParseNumber(JsonValue* value) {
    const size_t begin = index_;
    if (index_ < text_.size() && (text_[index_] == '-' || text_[index_] == '+')) {
      ++index_;
    }
    bool anyDigit = false;
    std::string integerPart;
    while (index_ < text_.size() && text_[index_] >= '0' && text_[index_] <= '9') {
      integerPart.push_back(text_[index_]);
      ++index_;
      anyDigit = true;
    }
    if (!anyDigit) {
      index_ = begin;
      return false;
    }
    long long integer = 0;
    for (size_t offset = 0; offset < integerPart.size(); ++offset) {
      integer = integer * 10 + static_cast<long long>(integerPart[offset] - '0');
    }
    if (begin < text_.size() && text_[begin] == '-') {
      integer = -integer;
    }
    value->kind = JsonValue::Kind::Number;
    value->integer = integer;
    value->decimal = static_cast<double>(integer);
    if (index_ < text_.size() && text_[index_] == '.') {
      ++index_;
      std::string fraction;
      while (index_ < text_.size() && text_[index_] >= '0' && text_[index_] <= '9') {
        fraction.push_back(text_[index_]);
        ++index_;
      }
      double scale = 0.1;
      for (size_t offset = 0; offset < fraction.size(); ++offset) {
        value->decimal += static_cast<double>(fraction[offset] - '0') * scale;
        scale *= 0.1;
      }
    }
    if (index_ < text_.size() && (text_[index_] == 'e' || text_[index_] == 'E')) {
      ++index_;
      if (index_ < text_.size() && (text_[index_] == '-' || text_[index_] == '+')) {
        ++index_;
      }
      while (index_ < text_.size() && text_[index_] >= '0' && text_[index_] <= '9') {
        ++index_;
      }
    }
    return true;
  }

  bool ParseString(std::wstring* out) {
    if (index_ >= text_.size() || text_[index_] != '"') {
      return false;
    }
    ++index_;
    std::string utf8;
    while (index_ < text_.size()) {
      const char character = text_[index_];
      if (character == '"') {
        ++index_;
        *out = Utf8ToWide(utf8);
        return true;
      }
      if (character != '\\') {
        utf8.push_back(character);
        ++index_;
        continue;
      }
      ++index_;
      if (index_ >= text_.size()) {
        return false;
      }
      const char escape = text_[index_++];
      switch (escape) {
        case '"':
          utf8.push_back('"');
          break;
        case '\\':
          utf8.push_back('\\');
          break;
        case '/':
          utf8.push_back('/');
          break;
        case 'b':
          utf8.push_back('\b');
          break;
        case 'f':
          utf8.push_back('\f');
          break;
        case 'n':
          utf8.push_back('\n');
          break;
        case 'r':
          utf8.push_back('\r');
          break;
        case 't':
          utf8.push_back('\t');
          break;
        case 'u': {
          unsigned int code = 0;
          if (!ParseHex4(&code)) {
            return false;
          }
          if (code >= 0xD800 && code <= 0xDBFF && index_ + 1 < text_.size() && text_[index_] == '\\' &&
              text_[index_ + 1] == 'u') {
            index_ += 2;
            unsigned int low = 0;
            if (!ParseHex4(&low)) {
              return false;
            }
            if (low >= 0xDC00 && low <= 0xDFFF) {
              code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00);
            }
          }
          AppendUtf8(code, &utf8);
          break;
        }
        default:
          return false;
      }
    }
    return false;
  }

  bool ParseHex4(unsigned int* value) {
    if (index_ + 4 > text_.size()) {
      return false;
    }
    unsigned int result = 0;
    for (int offset = 0; offset < 4; ++offset) {
      const char character = text_[index_ + static_cast<size_t>(offset)];
      unsigned int digit = 0;
      if (character >= '0' && character <= '9') {
        digit = static_cast<unsigned int>(character - '0');
      } else if (character >= 'a' && character <= 'f') {
        digit = static_cast<unsigned int>(character - 'a') + 10;
      } else if (character >= 'A' && character <= 'F') {
        digit = static_cast<unsigned int>(character - 'A') + 10;
      } else {
        return false;
      }
      result = result * 16 + digit;
    }
    index_ += 4;
    *value = result;
    return true;
  }

  static void AppendUtf8(unsigned int code, std::string* out) {
    if (code < 0x80) {
      out->push_back(static_cast<char>(code));
    } else if (code < 0x800) {
      out->push_back(static_cast<char>(0xC0 | (code >> 6)));
      out->push_back(static_cast<char>(0x80 | (code & 0x3F)));
    } else if (code < 0x10000) {
      out->push_back(static_cast<char>(0xE0 | (code >> 12)));
      out->push_back(static_cast<char>(0x80 | ((code >> 6) & 0x3F)));
      out->push_back(static_cast<char>(0x80 | (code & 0x3F)));
    } else {
      out->push_back(static_cast<char>(0xF0 | (code >> 18)));
      out->push_back(static_cast<char>(0x80 | ((code >> 12) & 0x3F)));
      out->push_back(static_cast<char>(0x80 | ((code >> 6) & 0x3F)));
      out->push_back(static_cast<char>(0x80 | (code & 0x3F)));
    }
  }

  bool ParseObject(JsonValue* value, int depth) {
    value->kind = JsonValue::Kind::Object;
    ++index_;  // '{'
    SkipSpace();
    if (index_ < text_.size() && text_[index_] == '}') {
      ++index_;
      return true;
    }
    for (;;) {
      SkipSpace();
      std::wstring key;
      if (!ParseString(&key)) {
        return false;
      }
      SkipSpace();
      if (index_ >= text_.size() || text_[index_] != ':') {
        return false;
      }
      ++index_;
      JsonValue member;
      if (!ParseValue(&member, depth + 1)) {
        return false;
      }
      value->members.emplace_back(key, std::move(member));
      SkipSpace();
      if (index_ < text_.size() && text_[index_] == ',') {
        ++index_;
        continue;
      }
      if (index_ < text_.size() && text_[index_] == '}') {
        ++index_;
        return true;
      }
      return false;
    }
  }

  bool ParseArray(JsonValue* value, int depth) {
    value->kind = JsonValue::Kind::Array;
    ++index_;  // '['
    SkipSpace();
    if (index_ < text_.size() && text_[index_] == ']') {
      ++index_;
      return true;
    }
    for (;;) {
      JsonValue item;
      if (!ParseValue(&item, depth + 1)) {
        return false;
      }
      value->items.push_back(std::move(item));
      SkipSpace();
      if (index_ < text_.size() && text_[index_] == ',') {
        ++index_;
        continue;
      }
      if (index_ < text_.size() && text_[index_] == ']') {
        ++index_;
        return true;
      }
      return false;
    }
  }

  const std::string& text_;
  size_t index_ = 0;
};

void EscapeToUtf8(const std::wstring& text, std::string* out) {
  static const char kHex[] = "0123456789abcdef";
  const std::string utf8 = WideToUtf8(text);
  for (size_t index = 0; index < utf8.size(); ++index) {
    const unsigned char character = static_cast<unsigned char>(utf8[index]);
    switch (character) {
      case '"':
        out->append("\\\"");
        break;
      case '\\':
        out->append("\\\\");
        break;
      case '\b':
        out->append("\\b");
        break;
      case '\f':
        out->append("\\f");
        break;
      case '\n':
        out->append("\\n");
        break;
      case '\r':
        out->append("\\r");
        break;
      case '\t':
        out->append("\\t");
        break;
      default:
        if (character < 0x20) {
          out->push_back('\\');
          out->push_back('u');
          out->push_back('0');
          out->push_back('0');
          out->push_back(kHex[(character >> 4) & 0x0F]);
          out->push_back(kHex[character & 0x0F]);
        } else {
          out->push_back(static_cast<char>(character));
        }
        break;
    }
  }
}

}  // namespace

const JsonValue* JsonValue::Member(const std::wstring& key) const {
  if (kind != Kind::Object) {
    return nullptr;
  }
  for (size_t index = 0; index < members.size(); ++index) {
    if (members[index].first == key) {
      return &members[index].second;
    }
  }
  return nullptr;
}

std::wstring JsonValue::MemberText(const std::wstring& key, const std::wstring& fallback) const {
  const JsonValue* member = Member(key);
  if (member == nullptr || member->kind != Kind::String) {
    return fallback;
  }
  return member->text;
}

long long JsonValue::MemberNumber(const std::wstring& key, long long fallback) const {
  const JsonValue* member = Member(key);
  if (member == nullptr) {
    return fallback;
  }
  if (member->kind == Kind::Number) {
    return member->integer;
  }
  if (member->kind == Kind::String) {
    unsigned long long parsed = 0;
    if (ParseUnsigned(member->text, &parsed)) {
      return static_cast<long long>(parsed);
    }
  }
  return fallback;
}

bool JsonParse(const std::string& utf8, JsonValue* value) {
  if (value == nullptr) {
    return false;
  }
  Parser parser(utf8);
  return parser.Parse(value);
}

bool JsonLookupText(const std::string& utf8, const std::wstring& path, std::wstring* text) {
  JsonValue root;
  if (!JsonParse(utf8, &root)) {
    return false;
  }
  const JsonValue* current = &root;
  size_t begin = 0;
  while (begin <= path.size()) {
    const size_t dot = path.find(L'.', begin);
    const std::wstring key = dot == std::wstring::npos ? path.substr(begin) : path.substr(begin, dot - begin);
    current = current->Member(key);
    if (current == nullptr) {
      return false;
    }
    if (dot == std::wstring::npos) {
      break;
    }
    begin = dot + 1;
  }
  if (current->kind == JsonValue::Kind::String) {
    if (text != nullptr) {
      *text = current->text;
    }
    return true;
  }
  if (current->kind == JsonValue::Kind::Number) {
    if (text != nullptr) {
      *text = Format(L"%lld", current->integer);
    }
    return true;
  }
  return false;
}

void JsonWriter::SetText(const std::wstring& key, const std::wstring& value) {
  for (size_t index = 0; index < fields_.size(); ++index) {
    if (fields_[index].key == key) {
      fields_[index].text = value;
      fields_[index].isText = true;
      return;
    }
  }
  Field field;
  field.key = key;
  field.text = value;
  field.isText = true;
  fields_.push_back(std::move(field));
}

void JsonWriter::SetNumber(const std::wstring& key, long long value) {
  for (size_t index = 0; index < fields_.size(); ++index) {
    if (fields_[index].key == key) {
      fields_[index].number = value;
      fields_[index].isText = false;
      return;
    }
  }
  Field field;
  field.key = key;
  field.number = value;
  field.isText = false;
  fields_.push_back(std::move(field));
}

std::string JsonWriter::ToUtf8() const {
  std::string out = "{";
  for (size_t index = 0; index < fields_.size(); ++index) {
    if (index > 0) {
      out.push_back(',');
    }
    out.push_back('"');
    EscapeToUtf8(fields_[index].key, &out);
    out.append("\":");
    if (fields_[index].isText) {
      out.push_back('"');
      EscapeToUtf8(fields_[index].text, &out);
      out.push_back('"');
    } else {
      const std::wstring number = Format(L"%lld", fields_[index].number);
      out.append(WideToUtf8(number));
    }
  }
  out.push_back('}');
  return out;
}

}  // namespace upd
