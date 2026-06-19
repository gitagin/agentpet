export type AssistantReplyTextFilter = {
  append: (text: string) => string;
  takeHiddenTexts: () => string[];
  reset: () => void;
};

const openingHiddenMarkers = new Set(["(", "\uff08"]);
const closingHiddenMarkers = new Set([")", "\uff09"]);
const hiddenEmphasisMarkers = new Set(["*", "\uff0a"]);

export type AssistantReplyVisibilityResult = {
  visibleText: string;
  hiddenTexts: string[];
};

export function createAssistantReplyTextFilter(): AssistantReplyTextFilter {
  let hiddenDepth = 0;
  let hiddenEmphasis = false;
  let parentheticalBuffer = "";
  let emphasisBuffer = "";
  let hiddenTexts: string[] = [];

  const pushHiddenText = (value: string) => {
    const normalized = normalizeHiddenAssistantReplyText(value);
    if (normalized) {
      hiddenTexts.push(normalized);
    }
  };

  return {
    append(text: string) {
      let visible = "";
      const chars = Array.from(text);
      for (let index = 0; index < chars.length; index += 1) {
        const char = chars[index];
        const nextChar = chars[index + 1];
        if (hiddenEmphasis) {
          if (hiddenEmphasisMarkers.has(char)) {
            hiddenEmphasis = false;
            pushHiddenText(emphasisBuffer);
            emphasisBuffer = "";
          } else {
            emphasisBuffer += char;
          }
          continue;
        }
        if (hiddenDepth > 0) {
          if (openingHiddenMarkers.has(char)) {
            hiddenDepth += 1;
            continue;
          }
          if (closingHiddenMarkers.has(char)) {
            hiddenDepth -= 1;
            if (hiddenDepth === 0) {
              pushHiddenText(parentheticalBuffer);
              parentheticalBuffer = "";
            }
            continue;
          }
          parentheticalBuffer += char;
          continue;
        }

        if (openingHiddenMarkers.has(char)) {
          hiddenDepth = 1;
          parentheticalBuffer = "";
          continue;
        }
        if (closingHiddenMarkers.has(char)) {
          continue;
        }
        if (hiddenEmphasisMarkers.has(char)) {
          if (nextChar && hiddenEmphasisMarkers.has(nextChar)) {
            visible += `${char}${nextChar}`;
            index += 1;
            continue;
          }
          hiddenEmphasis = true;
          emphasisBuffer = "";
          continue;
        }
        visible += char;
      }
      return visible;
    },
    takeHiddenTexts() {
      const texts = hiddenTexts;
      hiddenTexts = [];
      return texts;
    },
    reset() {
      hiddenDepth = 0;
      hiddenEmphasis = false;
      parentheticalBuffer = "";
      emphasisBuffer = "";
      hiddenTexts = [];
    },
  };
}

export function filterAssistantReplyText(text: string): AssistantReplyVisibilityResult {
  const filter = createAssistantReplyTextFilter();
  const visibleText = normalizeVisibleAssistantReplyText(filter.append(text));
  return {
    visibleText,
    hiddenTexts: filter.takeHiddenTexts(),
  };
}

export function stripAssistantHiddenReplyText(text: string): string {
  return filterAssistantReplyText(text).visibleText;
}

export function normalizeVisibleAssistantReplyText(text: string): string {
  return text
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\s+([,.;:!?\u3001\u3002\uff0c\uff1b\uff1a\uff01\uff1f])/g, "$1")
    .replace(/([\u3001\u3002\uff0c\uff1b\uff1a\uff01\uff1f])\s+/g, "$1");
}

function normalizeHiddenAssistantReplyText(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}
