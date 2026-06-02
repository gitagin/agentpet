import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const sourcePath = new URL("../src/services/petBubblePagination.ts", import.meta.url);
const source = await readFile(sourcePath, "utf8");
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
  },
});

const moduleUrl = `data:text/javascript;charset=utf-8,${encodeURIComponent(transpiled.outputText)}`;
const pagination = await import(moduleUrl);

const {
  getPetBubbleGraphemeCount,
  getPetBubblePageDelay,
  getPetBubbleVisualWeight,
  normalizePetBubbleText,
  paginatePetBubbleReply,
  petBubbleHardSplitWeight,
  petBubblePageDelayMs,
  petBubbleSegmentMinWeight,
  petBubbleSegmentMaxWeight,
  segmentPetBubbleText,
} = pagination;

const story = [
  "\u5c0f\u732b\u6258\u6258\u8ff7\u8def\u4e86\uff0c\u5b83\u60f3\u56de\u5bb6\uff0c\u548c\u5976\u5976\u4e00\u8d77\u5206\u4eab\u4eca\u5929\u7684\u89c1\u95fb\u3002",
  "\u5b83\u7a7f\u8fc7\u4e86\u6c99\u6c99\u54cd\u7684\u7af9\u6797\uff0c\u8fd8\u5dee\u70b9\u6389\u8fdb\u6eaa\u6d41\u91cc\u3002",
  "\u6bcf\u6b21\u5feb\u8981\u653e\u5f03\u7684\u65f6\u5019\uff0c\u5e78\u8fd0\u7684\u5c0f\u706f\u5c31\u4f1a\u4eae\u8d77\u6765\u3002",
  "\u6700\u540e\uff0c\u5b83\u770b\u5230\u4e86\u5bb6\u95e8\u53e3\u7684\u6696\u5149\u3002",
].join("");

const samples = [
  {
    name: "blank and emoji should merge",
    text: "\ud83d\ude0a\n\n\u4f60\u597d\u5440\uff01\u6211\u5728\u8fd9\u91cc\u966a\u4f60\u3002",
    forbidsBlank: true,
    forbidsWeakStandalone: true,
  },
  {
    name: "screenshot-like question",
    text: "\uff1f\ud83d\ude0a \u4f60\u6628\u5929\u662f\u6709\u4ec0\u4e48\u7279\u522b\u7684\u4e8b\u60c5\u60f3\u8bf4\uff0c\u8fd8\u662f\u60f3\u7ee7\u7eed\u804a\u804a\u5462\uff1f",
    forbidsWeakStandalone: true,
  },
  {
    name: "cat story",
    text: story,
    forbiddenAdjacent: ["\u6c99\u6c99\u54cd\u7684|\u7af9\u6797", "\u5c31\u4f1a\u4eae\u8d77|\u6765"],
  },
  {
    name: "quoted dialogue",
    text: "\u5c0f\u5154\u5b50\u8bf4\uff1a\u201c\u5929\u592a\u9ed1\u4e86\uff0c\u6211\u627e\u4e0d\u5230\u56de\u5bb6\u7684\u8def\u2026\u2026\u201d\u95ea\u95ea\u8f7b\u8f7b\u70b9\u4eae\u4e86\u81ea\u5df1\u7684\u5149\u3002",
  },
  {
    name: "long chinese without punctuation",
    text: "\u8fd9\u662f\u4e00\u6bb5\u5f88\u957f\u5f88\u957f\u4f46\u662f\u6ca1\u6709\u660e\u663e\u6807\u70b9\u7684\u4e2d\u6587\u5185\u5bb9\u7528\u6765\u9a8c\u8bc1\u5b89\u5168\u786c\u5207\u53ea\u7528\u5728\u5fc5\u8981\u7684\u65f6\u5019",
    allowsHardSplit: true,
  },
  {
    name: "markdown code block",
    text: '\u8fd9\u91cc\u6709\u4ee3\u7801\u5757\uff1a\n```ts\nconst answer = "\u95ea\u95ea\u4f1a\u53d1\u5149";\nconsole.log(answer);\n```\n\u4ee3\u7801\u5757\u5185\u5bb9\u5fc5\u987b\u539f\u6837\u4fdd\u7559\u3002',
    includes: 'const answer = "\u95ea\u95ea\u4f1a\u53d1\u5149";',
    allowsHardSplit: true,
  },
  {
    name: "url and english",
    text: "Open https://example.com/some/very/long/path?query=agent-pet and keep English spacing intact.",
    allowsHardSplit: true,
  },
  {
    name: "list",
    text: "- \u7b2c\u4e00\u6761\uff1a\u5148\u786e\u8ba4\u95ee\u9898\u3002\n- \u7b2c\u4e8c\u6761\uff1a\u4fee\u590d\u5206\u9875\u3002\n- \u7b2c\u4e09\u6761\uff1a\u9a8c\u8bc1\u4e0d\u4e22\u5b57\u3002",
  },
  {
    name: "emoji graphemes",
    text: "\u4eca\u5929\u5fc3\u60c5\u5f88\u597d\ud83d\ude0a\uff0c\u60f3\u542c\u4e00\u4e2a\u7761\u524d\u6545\u4e8b\ud83c\udf19\u3002Family \ud83d\udc68\u200d\ud83d\udc69\u200d\ud83d\udc67\u200d\ud83d\udc66 says hello! \u5f69\u8679\u65d7\ud83c\udff3\ufe0f\u200d\ud83c\udf08\u548c\u70b9\u8d5e\ud83d\udc4d\ud83c\udffd\u90fd\u4e0d\u80fd\u88ab\u5207\u574f\u3002",
    includes: "\ud83d\udc68\u200d\ud83d\udc69\u200d\ud83d\udc67\u200d\ud83d\udc66",
  },
];

function assertNoBrokenGraphemeBoundary(page, sampleName, pageIndex) {
  assert.doesNotMatch(page, /[\u200d\ufe0f]$/, `${sampleName}: page ${pageIndex} ends with a joiner or variation selector`);
  assert.doesNotMatch(page, /^[\u200d\ufe0f]/, `${sampleName}: page ${pageIndex} starts with a joiner or variation selector`);
  assert.doesNotMatch(page, /[\u{1f3fb}-\u{1f3ff}]$/u, `${sampleName}: page ${pageIndex} ends with an emoji skin tone modifier`);
  assert.doesNotMatch(page, /^[\u{1f3fb}-\u{1f3ff}]/u, `${sampleName}: page ${pageIndex} starts with an emoji skin tone modifier`);
}

function hasNaturalEnding(page) {
  return /[。！？!?；;…\n]$|[。！？!?；;…][”’」』》】）)]$/.test(page);
}

function isWeakStandalone(page) {
  const graphemes = segmentPetBubbleText(page.trim()).filter((grapheme) => grapheme.trim() !== "");
  return (
    graphemes.length > 0 &&
    graphemes.every((grapheme) =>
      /[。！？!?；;…,.:'"()[\]{}<>/\\|`~@#$%^&*_+=-]/u.test(grapheme) ||
      /\p{Extended_Pictographic}/u.test(grapheme),
    )
  );
}

assert.equal(petBubbleSegmentMaxWeight, 31, "semantic bubble segments should fit the fixed pet bubble");
assert.equal(petBubbleHardSplitWeight, 30, "hard split should be reserved for oversized unpunctuated text");
assert.equal(petBubbleSegmentMinWeight, 10, "short or weak segments should be merged with neighbors");

for (const sample of samples) {
  const pages = paginatePetBubbleReply(sample.text);
  assert.ok(pages.length > 0, `${sample.name}: expected at least one segment`);
  const normalized = normalizePetBubbleText(sample.text);
  assert.equal(pages.join(""), normalized, `${sample.name}: segments must reconstruct normalized text exactly`);
  assert.deepEqual(
    pages.flatMap((page) => segmentPetBubbleText(page)),
    segmentPetBubbleText(normalized),
    `${sample.name}: segments must preserve grapheme order`,
  );

  for (const [index, page] of pages.entries()) {
    const segmentNumber = index + 1;
    assert.ok(getPetBubbleGraphemeCount(page) > 0, `${sample.name}: segment ${segmentNumber} should not be empty`);
    assert.notEqual(page.trim(), "", `${sample.name}: segment ${segmentNumber} should not be blank`);
    if (sample.forbidsWeakStandalone || pages.length > 1) {
      assert.equal(isWeakStandalone(page), false, `${sample.name}: segment ${segmentNumber} should not be pure punctuation or emoji`);
    }
    assert.ok(
      getPetBubbleVisualWeight(page) <= petBubbleSegmentMaxWeight + 8,
      `${sample.name}: segment ${segmentNumber} is too long (${getPetBubbleVisualWeight(page)})`,
    );
    if (!sample.allowsHardSplit && index < pages.length - 1) {
      assert.ok(hasNaturalEnding(page), `${sample.name}: segment ${segmentNumber} should end at a natural boundary`);
    }
    const delay = getPetBubblePageDelay(page);
    assert.equal(delay, petBubblePageDelayMs, `${sample.name}: segment delay should be fixed (${delay})`);
    assertNoBrokenGraphemeBoundary(page, sample.name, segmentNumber);
  }

  if (sample.includes) {
    assert.ok(pages.join("").includes(sample.includes), `${sample.name}: expected phrase missing`);
  }
  for (const pair of sample.forbiddenAdjacent || []) {
    const [left, right] = pair.split("|");
    const leftPage = pages.findIndex((page) => page.endsWith(left));
    const rightPage = pages.findIndex((page) => page.startsWith(right));
    assert.notEqual(leftPage + 1, rightPage, `${sample.name}: should not split between "${left}" and "${right}"`);
  }
}

console.log(`validated ${samples.length} pet bubble semantic segments`);
