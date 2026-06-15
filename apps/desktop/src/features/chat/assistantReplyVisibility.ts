export type AssistantReplyTextFilter = {
  append: (text: string) => string;
  reset: () => void;
};

const openingHiddenMarkers = new Set(["(", "\uff08"]);
const closingHiddenMarkers = new Set([")", "\uff09"]);

export function createAssistantReplyTextFilter(): AssistantReplyTextFilter {
  let hiddenDepth = 0;

  return {
    append(text: string) {
      let visible = "";
      for (const char of text) {
        if (openingHiddenMarkers.has(char)) {
          hiddenDepth += 1;
          continue;
        }
        if (closingHiddenMarkers.has(char)) {
          if (hiddenDepth > 0) {
            hiddenDepth -= 1;
            continue;
          }
          continue;
        }
        if (hiddenDepth > 0) {
          continue;
        }
        visible += char;
      }
      return visible;
    },
    reset() {
      hiddenDepth = 0;
    },
  };
}

export function stripAssistantHiddenReplyText(text: string): string {
  return normalizeVisibleAssistantReplyText(createAssistantReplyTextFilter().append(text));
}

export function normalizeVisibleAssistantReplyText(text: string): string {
  return text
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\s+([,.;:!?\u3001\u3002\uff0c\uff1b\uff1a\uff01\uff1f])/g, "$1")
    .replace(/([\u3001\u3002\uff0c\uff1b\uff1a\uff01\uff1f])\s+/g, "$1");
}
