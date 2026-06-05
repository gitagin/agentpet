import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const currentFile = fileURLToPath(import.meta.url);
const __dirname = path.dirname(currentFile);
const repoRoot = path.resolve(__dirname, "../../..");

const scanRoots = [
  "apps/backend/app",
  "apps/desktop/electron",
  "apps/desktop/src",
  "apps/desktop/scripts",
];

const skippedDirectories = new Set([
  "node_modules",
  "dist",
  "release",
  "vendor",
  "__pycache__",
  ".pytest_cache",
]);

const scannedExtensions = new Set([
  ".cjs",
  ".js",
  ".mjs",
  ".py",
  ".ts",
  ".tsx",
]);

const suspiciousFragments = [
  [0x95c1, 0x739a],
  [0x5a11, 0x63f1],
  [0x95bb, 0x74a5],
  [0x5a34, 0x7cee],
  [0x95ba, 0x50e0],
  [0x95b8, 0x6a82],
  [0x6fde, 0x78bb],
  [0x934b, 0x6ec4],
  [0x6d93, 0x5a41],
  [0x6d93, 0x5b29],
  [0x93c8, 0x6944],
  [0x93c8, 0x63a5],
  [0x9431, 0x30e8],
  [0x6d7c, 0x6c2d],
  [0x5997, 0x5c90],
  [0x7039, 0x70b4],
  [0x5a34, 0x4f5d],
  [0x9286, 0x003f],
].map((codePoints) => String.fromCodePoint(...codePoints));

function* walk(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (skippedDirectories.has(entry.name)) {
      continue;
    }
    const absolutePath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      yield* walk(absolutePath);
      continue;
    }
    if (entry.isFile() && scannedExtensions.has(path.extname(entry.name))) {
      yield absolutePath;
    }
  }
}

const findings = [];
for (const root of scanRoots) {
  const absoluteRoot = path.join(repoRoot, root);
  if (!fs.existsSync(absoluteRoot)) {
    continue;
  }
  for (const file of walk(absoluteRoot)) {
    if (file === currentFile) {
      continue;
    }
    const text = fs.readFileSync(file, "utf8");
    const lines = text.split(/\r?\n/);
    lines.forEach((line, index) => {
      const fragment = suspiciousFragments.find((candidate) => line.includes(candidate));
      if (fragment) {
        findings.push({
          file: path.relative(repoRoot, file).replace(/\\/g, "/"),
          line: index + 1,
          fragment,
        });
      }
    });
  }
}

if (findings.length > 0) {
  console.error("Runtime mojibake validation failed:");
  for (const finding of findings) {
    console.error(`- ${finding.file}:${finding.line} contains ${JSON.stringify(finding.fragment)}`);
  }
  process.exit(1);
}

console.log("Runtime mojibake validation passed.");
