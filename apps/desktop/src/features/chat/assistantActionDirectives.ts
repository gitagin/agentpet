const actionDirectiveNames = new Set([
  "angry",
  "comfort",
  "cry",
  "happy",
  "memory",
  "pillow",
  "qaq",
  "smile",
  "smiling",
  "task",
  "think",
  "thinking",
  "todo",
  "wave",
  "waving",
  "wiki",
  "安慰",
  "爱心",
  "抱抱",
  "抱枕",
  "待机",
  "归档",
  "黑脸",
  "回忆",
  "记一下",
  "记忆",
  "开心",
  "哭",
  "默认",
  "难过",
  "陪伴",
  "庆祝",
  "任务",
  "生气",
  "思考",
  "提醒",
  "微笑",
  "温柔",
  "笑",
  "心疼",
  "星星",
  "疑惑",
  "整理",
  "资料",
]);

type DirectiveMatch = {
  index: number;
  value: string;
};

export function isAssistantActionDirective(value: string): boolean {
  const normalized = value
    .trim()
    .toLocaleLowerCase()
    .replace(/^[\s.,!?，。！？、…·~～-]+|[\s.,!?，。！？、…·~～-]+$/gu, "");
  return normalized.length > 0 && normalized.length <= 32 && actionDirectiveNames.has(normalized);
}

export function stripAssistantActionDirectivesFromMarkdown(markdown: string): string {
  return markdown
    .replace(/\(([^()\r\n]{1,64})\)|（([^（）\r\n]{1,64})）/gu, (match, ascii, fullWidth) =>
      isAssistantActionDirective(ascii ?? fullWidth ?? "") ? "" : match,
    )
    .replace(/(^|[^*])\*([^*\r\n]{1,64})\*(?!\*)/gmu, (match, prefix, value) =>
      isAssistantActionDirective(value) ? prefix : match,
    )
    .replace(/＊([^＊\r\n]{1,64})＊/gu, (match, value) =>
      isAssistantActionDirective(value) ? "" : match,
    );
}

export function extractAssistantActionDirectives(markdown: string): string[] {
  const matches: DirectiveMatch[] = [];
  collectMatches(markdown, /\(([^()\r\n]{1,64})\)|（([^（）\r\n]{1,64})）/gu, matches, (match) =>
    match[1] ?? match[2] ?? "",
  );
  collectMatches(markdown, /(^|[^*])\*([^*\r\n]{1,64})\*(?!\*)/gmu, matches, (match) => match[2] ?? "");
  collectMatches(markdown, /＊([^＊\r\n]{1,64})＊/gu, matches, (match) => match[1] ?? "");

  const seen = new Set<string>();
  return matches
    .sort((left, right) => left.index - right.index)
    .map((match) => match.value.trim())
    .filter((value) => {
      const key = value.toLocaleLowerCase();
      if (!value || seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
}

function collectMatches(
  markdown: string,
  pattern: RegExp,
  matches: DirectiveMatch[],
  valueFromMatch: (match: RegExpExecArray) => string,
) {
  for (const match of markdown.matchAll(pattern)) {
    const value = valueFromMatch(match);
    if (isAssistantActionDirective(value)) {
      matches.push({ index: match.index, value });
    }
  }
}
