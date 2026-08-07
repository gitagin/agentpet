import { isAssistantActionDirective } from "./assistantActionDirectives";

export type AssistantReplyTextFilter = {
  append: (text: string) => string;
  takeHiddenTexts: () => string[];
  reset: () => void;
};

const openingHiddenMarkers = new Set(["(", "\uff08"]);
const closingHiddenMarkers = new Set([")", "\uff09"]);

export type AssistantReplyVisibilityResult = {
  visibleText: string;
  hiddenTexts: string[];
};

export function createAssistantReplyTextFilter(): AssistantReplyTextFilter {
  let hiddenDepth = 0;
  let linkDestinationDepth = 0;
  let pendingLinkOpen = false;
  let parentheticalOpening = "";
  let parentheticalBuffer = "";
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
        if (linkDestinationDepth > 0) {
          visible += char;
          if (char === "(") {
            linkDestinationDepth += 1;
          } else if (char === ")") {
            linkDestinationDepth -= 1;
          }
          continue;
        }
        if (pendingLinkOpen) {
          if (char === "(") {
            visible += char;
            linkDestinationDepth = 1;
            pendingLinkOpen = false;
            continue;
          }
          pendingLinkOpen = false;
        }
        if (hiddenDepth > 0) {
          if (openingHiddenMarkers.has(char)) {
            hiddenDepth += 1;
            parentheticalBuffer += char;
            continue;
          }
          if (closingHiddenMarkers.has(char)) {
            hiddenDepth -= 1;
            if (hiddenDepth === 0) {
              if (isAssistantActionDirective(parentheticalBuffer)) {
                pushHiddenText(parentheticalBuffer);
              } else {
                visible += `${parentheticalOpening}${parentheticalBuffer}${char}`;
              }
              parentheticalOpening = "";
              parentheticalBuffer = "";
            } else {
              parentheticalBuffer += char;
            }
            continue;
          }
          parentheticalBuffer += char;
          continue;
        }

        if (openingHiddenMarkers.has(char)) {
          hiddenDepth = 1;
          parentheticalOpening = char;
          parentheticalBuffer = "";
          continue;
        }
        if (closingHiddenMarkers.has(char)) {
          visible += char;
          continue;
        }
        if (char === "]") {
          visible += char;
          pendingLinkOpen = true;
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
      linkDestinationDepth = 0;
      pendingLinkOpen = false;
      parentheticalOpening = "";
      parentheticalBuffer = "";
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
