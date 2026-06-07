export const petBubbleSegmentMaxWeight = 31;
export const petBubbleHardSplitWeight = 30;
export const petBubbleSegmentMinWeight = 10;
export const petBubblePageDelayMinMs = 1700;
export const petBubblePageDelayMaxMs = 3600;
export const petBubblePageDelayBaseMs = 900;
export const petBubblePageDelayPerWeightMs = 85;

type GraphemeSegment = {
  segment: string;
};

type GraphemeSegmenter = {
  segment(input: string): Iterable<GraphemeSegment>;
};

type SegmenterConstructor = new (
  locales?: string | string[],
  options?: { granularity?: "grapheme" },
) => GraphemeSegmenter;

function getGraphemeSegmenter() {
  const intlWithSegmenter = Intl as typeof Intl & { Segmenter?: SegmenterConstructor };
  return typeof intlWithSegmenter.Segmenter === "function"
    ? new intlWithSegmenter.Segmenter("zh", { granularity: "grapheme" })
    : null;
}

export function segmentPetBubbleText(text: string) {
  const segmenter = getGraphemeSegmenter();
  return segmenter ? Array.from(segmenter.segment(text), (item) => item.segment) : Array.from(text);
}

export function normalizePetBubbleText(text: string) {
  return text
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{2,}/g, "\n")
    .trim();
}

export function normalizePetBubblePagesForCompare(text: string) {
  return normalizePetBubbleText(text);
}

export function getPetBubbleGraphemeCount(text: string) {
  return segmentPetBubbleText(text).length;
}

function isAsciiLetterOrDigit(grapheme: string) {
  return /^[A-Za-z0-9]$/.test(grapheme);
}

function isAsciiWhitespace(grapheme: string) {
  return grapheme === " ";
}

function isNarrowPunctuation(grapheme: string) {
  return /^[,.!?;:'"()[\]{}<>/\\|`~@#$%^&*_+=-]$/.test(grapheme);
}

function isEmojiLike(grapheme: string) {
  return /\p{Extended_Pictographic}/u.test(grapheme);
}

function isFullWidthOrCjk(grapheme: string) {
  return /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\u3000-\u303f\uff00-\uffef]/u.test(grapheme);
}

function isSentenceBoundary(grapheme: string) {
  return /[。！？!?；;…]/u.test(grapheme);
}

function isSoftBoundary(grapheme: string) {
  return /[，,、：:\s]/u.test(grapheme);
}

function isClosingQuote(grapheme: string) {
  return /[”’」』》】）)]/u.test(grapheme);
}

export function getPetBubbleVisualWeight(text: string) {
  return segmentPetBubbleText(text).reduce((total, grapheme) => total + getPetBubbleGraphemeWeight(grapheme), 0);
}

export function getPetBubbleGraphemeWeight(grapheme: string) {
  if (grapheme === "\n") {
    return 1;
  }
  if (isAsciiWhitespace(grapheme) || isNarrowPunctuation(grapheme)) {
    return 0.35;
  }
  if (isAsciiLetterOrDigit(grapheme)) {
    return 0.55;
  }
  if (isEmojiLike(grapheme)) {
    return 1.15;
  }
  if (isFullWidthOrCjk(grapheme)) {
    return 1;
  }
  return 0.8;
}

function isBlankSegment(segment: string) {
  return segment.trim().length === 0;
}

function isWeakSegment(segment: string) {
  const graphemes = segmentPetBubbleText(segment.trim()).filter((grapheme) => grapheme.trim() !== "");
  return graphemes.length > 0 && graphemes.every((grapheme) => isSentenceBoundary(grapheme) || isClosingQuote(grapheme) || isNarrowPunctuation(grapheme) || isEmojiLike(grapheme));
}

function shouldMergeSegments(current: string, next: string) {
  const combinedWeight = getPetBubbleVisualWeight(current + next);
  if (combinedWeight > petBubbleSegmentMaxWeight + 6) {
    return false;
  }
  return (
    isBlankSegment(current) ||
    isBlankSegment(next) ||
    isWeakSegment(current) ||
    isWeakSegment(next) ||
    getPetBubbleVisualWeight(current) < petBubbleSegmentMinWeight
  );
}

function pushNaturalSegment(segments: string[], segment: string) {
  if (!segment) {
    return;
  }
  if (isBlankSegment(segment)) {
    if (segments.length > 0) {
      segments[segments.length - 1] += segment;
    }
    return;
  }
  segments.push(segment);
}

function splitNaturalSegments(text: string) {
  const graphemes = segmentPetBubbleText(text);
  const segments: string[] = [];
  let current = "";

  for (let index = 0; index < graphemes.length; index += 1) {
    const grapheme = graphemes[index];

    if (grapheme === "\n") {
      if (current) {
        current += grapheme;
        pushNaturalSegment(segments, current);
        current = "";
      } else if (segments.length > 0) {
        segments[segments.length - 1] += grapheme;
      }
      continue;
    }

    current += grapheme;
    if (!isSentenceBoundary(grapheme)) {
      continue;
    }

    while (index + 1 < graphemes.length && isClosingQuote(graphemes[index + 1])) {
      index += 1;
      current += graphemes[index];
    }
    pushNaturalSegment(segments, current);
    current = "";
  }

  pushNaturalSegment(segments, current);
  return segments;
}

function splitLongPetBubbleSegment(segment: string) {
  const graphemes = segmentPetBubbleText(segment);
  const parts: string[] = [];
  let current = "";
  let currentWeight = 0;
  let lastSoftBoundaryIndex = -1;

  for (const grapheme of graphemes) {
    const weight = getPetBubbleGraphemeWeight(grapheme);
    if (current && currentWeight + weight > petBubbleHardSplitWeight) {
      if (lastSoftBoundaryIndex > 0) {
        parts.push(current.slice(0, lastSoftBoundaryIndex));
        current = current.slice(lastSoftBoundaryIndex);
        currentWeight = getPetBubbleVisualWeight(current);
      } else {
        parts.push(current);
        current = "";
        currentWeight = 0;
      }
      lastSoftBoundaryIndex = -1;
    }

    current += grapheme;
    currentWeight += weight;
    if (isSoftBoundary(grapheme)) {
      lastSoftBoundaryIndex = current.length;
    }
  }

  if (current) {
    parts.push(current);
  }
  return parts;
}

function compactWeakSegments(segments: string[]) {
  const compacted: string[] = [];

  for (const segment of segments) {
    if (!segment) {
      continue;
    }
    if (isBlankSegment(segment)) {
      if (compacted.length > 0) {
        compacted[compacted.length - 1] += segment;
      }
      continue;
    }

    if (compacted.length > 0 && shouldMergeSegments(compacted[compacted.length - 1], segment)) {
      compacted[compacted.length - 1] += segment;
    } else {
      compacted.push(segment);
    }
  }

  for (let index = 0; index < compacted.length - 1; index += 1) {
    if (isWeakSegment(compacted[index]) || getPetBubbleVisualWeight(compacted[index]) < petBubbleSegmentMinWeight) {
      compacted[index + 1] = compacted[index] + compacted[index + 1];
      compacted.splice(index, 1);
      index -= 1;
    }
  }

  if (compacted.length > 1) {
    const lastIndex = compacted.length - 1;
    if (isWeakSegment(compacted[lastIndex]) || getPetBubbleVisualWeight(compacted[lastIndex]) < petBubbleSegmentMinWeight) {
      compacted[lastIndex - 1] += compacted[lastIndex];
      compacted.pop();
    }
  }

  return compacted;
}

export function paginatePetBubbleReply(text: string) {
  const normalized = normalizePetBubbleText(text);
  if (!normalized) {
    return [];
  }

  const splitSegments = splitNaturalSegments(normalized).flatMap((segment) =>
    getPetBubbleVisualWeight(segment) > petBubbleSegmentMaxWeight
      ? splitLongPetBubbleSegment(segment)
      : [segment],
  );
  return compactWeakSegments(splitSegments);
}

export function getPetBubblePageDelay(page: string) {
  const delay = petBubblePageDelayBaseMs + getPetBubbleVisualWeight(page) * petBubblePageDelayPerWeightMs;
  return Math.round(Math.min(petBubblePageDelayMaxMs, Math.max(petBubblePageDelayMinMs, delay)));
}
