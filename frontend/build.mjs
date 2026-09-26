// 构建脚本：把 index.html、public/ 下的静态资源复制进 dist/，并把 rules.md
// 的游戏规则转换成页面数据注入。页面本身没有框架，构建只是组装静态文件。
import { cpSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL(".", import.meta.url));
const dist = join(root, "dist");

mkdirSync(dist, { recursive: true });
cpSync(join(root, "index.html"), join(dist, "index.html"));
cpSync(join(root, "public"), dist, { recursive: true });

// —— rules.md → 页面数据 ——
// 支持的写法：`## 标题` 开新折叠节；`### 标题` 节内小标题；`- x` 无序列表；
// `1. x` 有序列表；`**术语**：说明` 单独成段时渲染为术语表；其余段落按普通文字输出。
function parseRules(markdown) {
  const sections = [];
  let current = null;
  let list = null;
  const flushList = () => {
    if (list && current) current.blocks.push(list);
    list = null;
  };
  const flushTerms = () => {
    if (current && current._terms.length) {
      current.blocks.push({ type: "terms", terms: current._terms });
      current._terms = [];
    }
  };
  const flushParagraph = (lines) => {
    if (!current || !lines.length) return;
    const text = lines.join("\n");
    const term = text.match(/^\*\*(.+?)\*\*[:：](.*)$/s);
    if (term) {
      current._terms.push({ term: term[1], text: term[2].trim() });
    } else {
      flushTerms();
      current.blocks.push({ type: "p", text });
    }
  };
  let paragraph = [];
  for (const raw of markdown.split(/\r?\n/)) {
    const line = raw.trimEnd();
    const heading = line.match(/^##\s+(.+)$/);
    const subheading = line.match(/^###\s+(.+)$/);
    const bullet = line.match(/^[-*]\s+(.+)$/);
    const ordered = line.match(/^\d+[.、]\s+(.+)$/);
    if (heading) {
      flushParagraph(paragraph);
      paragraph = [];
      flushList();
      flushTerms();
      current = { title: heading[1].trim(), blocks: [], _terms: [] };
      sections.push(current);
    } else if (subheading) {
      flushParagraph(paragraph);
      paragraph = [];
      flushList();
      flushTerms();
      if (current) current.blocks.push({ type: "h3", text: subheading[1].trim() });
    } else if (bullet || ordered) {
      flushParagraph(paragraph);
      paragraph = [];
      if (!list || list.type !== (bullet ? "ul" : "ol")) {
        flushTerms();
        list = { type: bullet ? "ul" : "ol", items: [] };
      }
      list.items.push((bullet || ordered)[1].trim());
    } else if (!line.trim()) {
      flushParagraph(paragraph);
      paragraph = [];
      flushList();
      flushTerms();
    } else {
      flushList();
      paragraph.push(line.trim());
    }
  }
  flushParagraph(paragraph);
  for (const section of sections) delete section._terms;
  return sections;
}

const rules = parseRules(readFileSync(join(root, "rules.md"), "utf8"));
if (!rules.length) throw new Error("rules.md 没有解析出任何内容");

let html = readFileSync(join(dist, "index.html"), "utf8");
const inject = (token, value) => {
  if (!html.includes(token)) throw new Error(`index.html 缺少占位符 ${token}`);
  html = html.replace(token, value);
};
// 规则数据以 JSON 字面量注入；</script> 之类的序列在 JSON 里转义掉。
inject("var RULES_PLACEHOLDER", `var RULES = ${JSON.stringify(rules).replace(/</g, "\\u003c")}`);
inject("<!--BUILD-STAMP-->", new Date().toISOString().slice(0, 10));

writeFileSync(join(dist, "index.html"), html);
console.log("前端页面已构建到 frontend/dist");
