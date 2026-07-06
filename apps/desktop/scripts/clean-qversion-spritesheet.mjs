import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync, inflateSync } from "node:zlib";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const desktopRoot = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(desktopRoot, "..", "..");
const petRoot = path.join(desktopRoot, "public", "pets", "agent-pet-neko");
const manifestPath = path.join(petRoot, "pet.json");
const inputPath = path.join(petRoot, "spritesheet.png");
const outputPath = path.join(petRoot, "spritesheet-clean.png");
const qaDir = path.join(repoRoot, "output", "qversion-cleaning");

const transparentAlpha = 4;
const edgeExpansionPasses = 3;

const crcTable = new Uint32Array(256);
for (let n = 0; n < 256; n += 1) {
  let c = n;
  for (let k = 0; k < 8; k += 1) {
    c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  }
  crcTable[n] = c >>> 0;
}

function crc32(buffer) {
  let c = 0xffffffff;
  for (let index = 0; index < buffer.length; index += 1) {
    c = crcTable[(c ^ buffer[index]) & 0xff] ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data = Buffer.alloc(0)) {
  const typeBuffer = Buffer.from(type, "ascii");
  const out = Buffer.alloc(12 + data.length);
  out.writeUInt32BE(data.length, 0);
  typeBuffer.copy(out, 4);
  data.copy(out, 8);
  out.writeUInt32BE(crc32(Buffer.concat([typeBuffer, data])), 8 + data.length);
  return out;
}

function readPng(filePath) {
  const buffer = readFileSync(filePath);
  const signature = buffer.subarray(0, 8);
  if (!signature.equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
    throw new Error(`${filePath} is not a PNG file.`);
  }

  let offset = 8;
  let width = 0;
  let height = 0;
  let colorType = 0;
  const idatParts = [];

  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.subarray(offset + 4, offset + 8).toString("ascii");
    const data = buffer.subarray(offset + 8, offset + 8 + length);
    offset += 12 + length;

    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      const bitDepth = data[8];
      colorType = data[9];
      const compression = data[10];
      const filter = data[11];
      const interlace = data[12];
      if (bitDepth !== 8 || compression !== 0 || filter !== 0 || interlace !== 0) {
        throw new Error(`${filePath} uses unsupported PNG settings.`);
      }
      if (colorType !== 2 && colorType !== 6) {
        throw new Error(`${filePath} must be RGB or RGBA PNG.`);
      }
    } else if (type === "IDAT") {
      idatParts.push(data);
    } else if (type === "IEND") {
      break;
    }
  }

  const channels = colorType === 6 ? 4 : 3;
  const bytesPerPixel = channels;
  const stride = width * channels;
  const inflated = inflateSync(Buffer.concat(idatParts));
  const rgba = new Uint8Array(width * height * 4);
  const previous = new Uint8Array(stride);
  const current = new Uint8Array(stride);
  let inputOffset = 0;

  for (let y = 0; y < height; y += 1) {
    const filterType = inflated[inputOffset];
    inputOffset += 1;
    current.set(inflated.subarray(inputOffset, inputOffset + stride));
    inputOffset += stride;

    for (let x = 0; x < stride; x += 1) {
      const left = x >= bytesPerPixel ? current[x - bytesPerPixel] : 0;
      const up = previous[x] ?? 0;
      const upperLeft = x >= bytesPerPixel ? previous[x - bytesPerPixel] : 0;
      if (filterType === 1) {
        current[x] = (current[x] + left) & 0xff;
      } else if (filterType === 2) {
        current[x] = (current[x] + up) & 0xff;
      } else if (filterType === 3) {
        current[x] = (current[x] + Math.floor((left + up) / 2)) & 0xff;
      } else if (filterType === 4) {
        const p = left + up - upperLeft;
        const pa = Math.abs(p - left);
        const pb = Math.abs(p - up);
        const pc = Math.abs(p - upperLeft);
        const predictor = pa <= pb && pa <= pc ? left : pb <= pc ? up : upperLeft;
        current[x] = (current[x] + predictor) & 0xff;
      } else if (filterType !== 0) {
        throw new Error(`${filePath} uses unsupported PNG filter ${filterType}.`);
      }
    }

    for (let x = 0; x < width; x += 1) {
      const src = x * channels;
      const dst = (y * width + x) * 4;
      rgba[dst] = current[src];
      rgba[dst + 1] = current[src + 1];
      rgba[dst + 2] = current[src + 2];
      rgba[dst + 3] = channels === 4 ? current[src + 3] : 255;
    }
    previous.set(current);
  }

  return { filePath, width, height, data: rgba };
}

function writePng(filePath, image) {
  mkdirSync(path.dirname(filePath), { recursive: true });
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(image.width, 0);
  ihdr.writeUInt32BE(image.height, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  const stride = image.width * 4;
  const raw = Buffer.alloc((stride + 1) * image.height);
  for (let y = 0; y < image.height; y += 1) {
    const rowStart = y * (stride + 1);
    raw[rowStart] = 0;
    Buffer.from(image.data.buffer, image.data.byteOffset + y * stride, stride).copy(raw, rowStart + 1);
  }

  const png = Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND"),
  ]);
  writeFileSync(filePath, png);
}

function pixelOffset(width, x, y) {
  return (y * width + x) * 4;
}

function readMatteKind(data, offset) {
  const red = data[offset];
  const green = data[offset + 1];
  const blue = data[offset + 2];
  const alpha = data[offset + 3];
  if (alpha <= transparentAlpha) {
    return null;
  }

  const redGreenGap = red - green;
  const blueGreenGap = blue - green;
  const magentaLift = (red + blue) / 2 - green;
  const redBlueGap = Math.abs(red - blue);

  if (
    red >= 185 &&
    blue >= 145 &&
    green <= 132 &&
    redGreenGap >= 65 &&
    blueGreenGap >= 35 &&
    magentaLift >= 55 &&
    redBlueGap <= 125
  ) {
    return "strong";
  }

  if (
    red >= 55 &&
    blue >= 55 &&
    green <= 62 &&
    redGreenGap >= 34 &&
    blueGreenGap >= 34 &&
    magentaLift >= 36 &&
    redBlueGap <= 105
  ) {
    return "dark";
  }

  if (
    red >= 92 &&
    blue >= 82 &&
    green <= 96 &&
    redGreenGap >= 24 &&
    blueGreenGap >= 18 &&
    magentaLift >= 27 &&
    redBlueGap <= 118
  ) {
    return "weak";
  }

  return null;
}

function isHighSaturationPinkPurple(data, offset) {
  const red = data[offset];
  const green = data[offset + 1];
  const blue = data[offset + 2];
  return (
    data[offset + 3] > transparentAlpha &&
    red >= 180 &&
    blue >= 130 &&
    green <= 135 &&
    red - green >= 55 &&
    blue - green >= 25 &&
    (red + blue) / 2 - green >= 50
  );
}

function frameKey(row, column) {
  return `${row}:${column}`;
}

function cleanFrame(source, cleaned, width, height, frame, report) {
  const { row, column, left, top, right, bottom } = frame;
  const frameWidth = right - left;
  const frameHeight = bottom - top;
  const backgroundMask = new Uint8Array(frameWidth * frameHeight);
  const queue = new Int32Array(frameWidth * frameHeight);
  let queueStart = 0;
  let queueEnd = 0;

  const localIndex = (x, y) => (y - top) * frameWidth + (x - left);
  const enqueue = (x, y) => {
    const local = localIndex(x, y);
    if (backgroundMask[local]) {
      return;
    }
    const offset = pixelOffset(width, x, y);
    if (source[offset + 3] > transparentAlpha && !readMatteKind(source, offset)) {
      return;
    }
    backgroundMask[local] = 1;
    queue[queueEnd] = y * width + x;
    queueEnd += 1;
  };

  for (let x = left; x < right; x += 1) {
    enqueue(x, top);
    enqueue(x, bottom - 1);
  }
  for (let y = top; y < bottom; y += 1) {
    enqueue(left, y);
    enqueue(right - 1, y);
  }

  const changedOffsets = new Set();
  let connectedClearedPixels = 0;
  let edgeClearedPixels = 0;
  let edgeFadedPixels = 0;
  let candidatePixels = 0;
  let highSaturationCandidatePixels = 0;

  while (queueStart < queueEnd) {
    const absoluteIndex = queue[queueStart];
    queueStart += 1;
    const y = Math.floor(absoluteIndex / width);
    const x = absoluteIndex - y * width;
    const offset = absoluteIndex * 4;
    const kind = readMatteKind(source, offset);
    if (kind) {
      if (cleaned[offset + 3] !== 0) {
        cleaned[offset + 3] = 0;
        changedOffsets.add(offset);
        connectedClearedPixels += 1;
      }
    }

    if (x > left) {
      enqueue(x - 1, y);
    }
    if (x < right - 1) {
      enqueue(x + 1, y);
    }
    if (y > top) {
      enqueue(x, y - 1);
    }
    if (y < bottom - 1) {
      enqueue(x, y + 1);
    }
  }

  for (let y = top; y < bottom; y += 1) {
    for (let x = left; x < right; x += 1) {
      const offset = pixelOffset(width, x, y);
      if (readMatteKind(source, offset)) {
        candidatePixels += 1;
      }
      if (isHighSaturationPinkPurple(source, offset)) {
        highSaturationCandidatePixels += 1;
      }
    }
  }

  for (let pass = 0; pass < edgeExpansionPasses; pass += 1) {
    const changes = [];
    for (let y = top; y < bottom; y += 1) {
      for (let x = left; x < right; x += 1) {
        const offset = pixelOffset(width, x, y);
        if (cleaned[offset + 3] <= transparentAlpha) {
          continue;
        }
        const kind = readMatteKind(source, offset);
        if (!kind || !touchesTransparentOrBackground(cleaned, backgroundMask, width, frameWidth, left, top, right, bottom, x, y)) {
          continue;
        }
        changes.push({ offset, kind });
      }
    }

    for (const { offset, kind } of changes) {
      const beforeAlpha = cleaned[offset + 3];
      if (kind === "strong" || kind === "dark") {
        cleaned[offset + 3] = 0;
        edgeClearedPixels += changedOffsets.has(offset) ? 0 : 1;
        changedOffsets.add(offset);
      } else {
        const nextAlpha = Math.min(beforeAlpha, Math.round(beforeAlpha * 0.25));
        cleaned[offset + 3] = nextAlpha;
        if (nextAlpha < beforeAlpha && !changedOffsets.has(offset)) {
          edgeFadedPixels += 1;
          changedOffsets.add(offset);
        }
      }
    }
  }

  let retainedVisiblePixels = 0;
  for (let y = top; y < bottom; y += 1) {
    for (let x = left; x < right; x += 1) {
      if (cleaned[pixelOffset(width, x, y) + 3] > transparentAlpha) {
        retainedVisiblePixels += 1;
      }
    }
  }

  const cleanedPixels = changedOffsets.size;
  const preservedCandidatePixels = Math.max(0, candidatePixels - cleanedPixels);
  report.frames.push({
    key: frameKey(row, column),
    row,
    column,
    sourceX: left,
    sourceY: top,
    candidatePixels,
    highSaturationCandidatePixels,
    cleanedPixels,
    connectedClearedPixels,
    edgeClearedPixels,
    edgeFadedPixels,
    preservedCandidatePixels,
    retainedVisiblePixels,
  });
  report.totalCandidatePixels += candidatePixels;
  report.totalHighSaturationCandidatePixels += highSaturationCandidatePixels;
  report.totalCleanedPixels += cleanedPixels;
  report.totalClearedPixels += connectedClearedPixels + edgeClearedPixels;
  report.totalFadedPixels += edgeFadedPixels;
  report.preservedCandidatePixels += preservedCandidatePixels;
  report.preservedVisiblePixels += retainedVisiblePixels;
}

function touchesTransparentOrBackground(cleaned, backgroundMask, width, frameWidth, left, top, right, bottom, x, y) {
  for (let dy = -1; dy <= 1; dy += 1) {
    const nextY = y + dy;
    if (nextY < top || nextY >= bottom) {
      continue;
    }
    for (let dx = -1; dx <= 1; dx += 1) {
      if (dx === 0 && dy === 0) {
        continue;
      }
      const nextX = x + dx;
      if (nextX < left || nextX >= right) {
        continue;
      }
      const local = (nextY - top) * frameWidth + (nextX - left);
      if (backgroundMask[local] || cleaned[pixelOffset(width, nextX, nextY) + 3] <= transparentAlpha) {
        return true;
      }
    }
  }
  return false;
}

function cropImage(image, left, top, width, height) {
  const out = blankImage(width, height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const srcX = left + x;
      const srcY = top + y;
      if (srcX < 0 || srcX >= image.width || srcY < 0 || srcY >= image.height) {
        continue;
      }
      const src = pixelOffset(image.width, srcX, srcY);
      const dst = pixelOffset(width, x, y);
      out.data[dst] = image.data[src];
      out.data[dst + 1] = image.data[src + 1];
      out.data[dst + 2] = image.data[src + 2];
      out.data[dst + 3] = image.data[src + 3];
    }
  }
  return out;
}

function blankImage(width, height) {
  return { width, height, data: new Uint8Array(width * height * 4) };
}

function checkerImage(width, height, dark = [18, 18, 22], light = [45, 39, 48]) {
  const out = blankImage(width, height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const color = (Math.floor(x / 8) + Math.floor(y / 8)) % 2 === 0 ? dark : light;
      const offset = pixelOffset(width, x, y);
      out.data[offset] = color[0];
      out.data[offset + 1] = color[1];
      out.data[offset + 2] = color[2];
      out.data[offset + 3] = 255;
    }
  }
  return out;
}

function alphaComposite(target, source, left, top, scale = 1) {
  for (let y = 0; y < source.height; y += 1) {
    for (let x = 0; x < source.width; x += 1) {
      const srcOffset = pixelOffset(source.width, x, y);
      const alpha = source.data[srcOffset + 3] / 255;
      if (alpha <= 0) {
        continue;
      }
      for (let sy = 0; sy < scale; sy += 1) {
        for (let sx = 0; sx < scale; sx += 1) {
          const dstX = left + x * scale + sx;
          const dstY = top + y * scale + sy;
          if (dstX < 0 || dstX >= target.width || dstY < 0 || dstY >= target.height) {
            continue;
          }
          const dstOffset = pixelOffset(target.width, dstX, dstY);
          target.data[dstOffset] = Math.round(source.data[srcOffset] * alpha + target.data[dstOffset] * (1 - alpha));
          target.data[dstOffset + 1] = Math.round(
            source.data[srcOffset + 1] * alpha + target.data[dstOffset + 1] * (1 - alpha),
          );
          target.data[dstOffset + 2] = Math.round(
            source.data[srcOffset + 2] * alpha + target.data[dstOffset + 2] * (1 - alpha),
          );
          target.data[dstOffset + 3] = 255;
        }
      }
    }
  }
}

function drawRect(image, left, top, width, height, color) {
  for (let y = top; y < top + height; y += 1) {
    for (let x = left; x < left + width; x += 1) {
      if (x < 0 || x >= image.width || y < 0 || y >= image.height) {
        continue;
      }
      const offset = pixelOffset(image.width, x, y);
      image.data[offset] = color[0];
      image.data[offset + 1] = color[1];
      image.data[offset + 2] = color[2];
      image.data[offset + 3] = color[3] ?? 255;
    }
  }
}

function makeBeforeAfterContactSheet(source, cleaned, frames, stats) {
  const selected = stats.frames
    .filter((frame) => frame.cleanedPixels > 0)
    .sort((a, b) => b.cleanedPixels - a.cleanedPixels)
    .slice(0, 12);
  const frameWidth = frames[0].right - frames[0].left;
  const frameHeight = frames[0].bottom - frames[0].top;
  const gap = 12;
  const itemWidth = frameWidth * 2 + 6;
  const itemHeight = frameHeight + 10;
  const columns = 3;
  const rows = Math.ceil(selected.length / columns) || 1;
  const sheet = checkerImage(columns * itemWidth + gap * (columns + 1), rows * itemHeight + gap * (rows + 1));

  selected.forEach((frameStats, index) => {
    const frame = frames.find((candidate) => candidate.row === frameStats.row && candidate.column === frameStats.column);
    if (!frame) {
      return;
    }
    const col = index % columns;
    const row = Math.floor(index / columns);
    const x = gap + col * (itemWidth + gap);
    const y = gap + row * (itemHeight + gap);
    drawRect(sheet, x, y, frameWidth, 4, [188, 37, 188, 255]);
    drawRect(sheet, x + frameWidth + 6, y, frameWidth, 4, [71, 194, 157, 255]);
    alphaComposite(sheet, cropImage(source, frame.left, frame.top, frameWidth, frameHeight), x, y + 6);
    alphaComposite(sheet, cropImage(cleaned, frame.left, frame.top, frameWidth, frameHeight), x + frameWidth + 6, y + 6);
  });

  return sheet;
}

function makeProblemFrameCrops(source, cleaned, frames, stats) {
  const selected = stats.frames
    .filter((frame) => frame.cleanedPixels > 0)
    .sort((a, b) => b.cleanedPixels - a.cleanedPixels)
    .slice(0, 8);
  const cropSize = 56;
  const scale = 4;
  const gap = 12;
  const itemWidth = cropSize * scale * 2 + 6;
  const itemHeight = cropSize * scale + 8;
  const sheet = checkerImage(itemWidth + gap * 2, selected.length * itemHeight + gap * (selected.length + 1));

  selected.forEach((frameStats, index) => {
    const frame = frames.find((candidate) => candidate.row === frameStats.row && candidate.column === frameStats.column);
    if (!frame) {
      return;
    }
    const center = findChangedCenter(source, cleaned, frame);
    const cropLeft = Math.max(frame.left, Math.min(frame.right - cropSize, center.x - Math.floor(cropSize / 2)));
    const cropTop = Math.max(frame.top, Math.min(frame.bottom - cropSize, center.y - Math.floor(cropSize / 2)));
    const x = gap;
    const y = gap + index * (itemHeight + gap);
    drawRect(sheet, x, y, cropSize * scale, 4, [188, 37, 188, 255]);
    drawRect(sheet, x + cropSize * scale + 6, y, cropSize * scale, 4, [71, 194, 157, 255]);
    alphaComposite(sheet, cropImage(source, cropLeft, cropTop, cropSize, cropSize), x, y + 6, scale);
    alphaComposite(sheet, cropImage(cleaned, cropLeft, cropTop, cropSize, cropSize), x + cropSize * scale + 6, y + 6, scale);
  });

  return sheet;
}

function findChangedCenter(source, cleaned, frame) {
  let sumX = 0;
  let sumY = 0;
  let count = 0;
  for (let y = frame.top; y < frame.bottom; y += 1) {
    for (let x = frame.left; x < frame.right; x += 1) {
      const offset = pixelOffset(source.width, x, y);
      if (source.data[offset + 3] !== cleaned.data[offset + 3]) {
        sumX += x;
        sumY += y;
        count += 1;
      }
    }
  }
  if (!count) {
    return { x: frame.left + 28, y: frame.top + 28 };
  }
  return { x: Math.round(sumX / count), y: Math.round(sumY / count) };
}

function makeFrames(manifest, width, height) {
  const cellWidth = Number(manifest.cell?.width) || 192;
  const cellHeight = Number(manifest.cell?.height) || 208;
  const columns = Number(manifest.layout?.columns) || Math.floor(width / cellWidth);
  const rows = Number(manifest.layout?.rows) || Math.floor(height / cellHeight);
  const frames = [];
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      frames.push({
        row,
        column,
        left: column * cellWidth,
        top: row * cellHeight,
        right: Math.min(width, (column + 1) * cellWidth),
        bottom: Math.min(height, (row + 1) * cellHeight),
      });
    }
  }
  return frames;
}

function countVisiblePixels(image) {
  let count = 0;
  for (let offset = 0; offset < image.data.length; offset += 4) {
    if (image.data[offset + 3] > transparentAlpha) {
      count += 1;
    }
  }
  return count;
}

function main() {
  mkdirSync(qaDir, { recursive: true });
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const source = readPng(inputPath);
  const cleaned = { width: source.width, height: source.height, data: new Uint8Array(source.data) };
  const frames = makeFrames(manifest, source.width, source.height);
  const report = {
    inputPath,
    outputPath,
    inputSize: { width: source.width, height: source.height },
    outputSize: { width: cleaned.width, height: cleaned.height },
    cell: manifest.cell,
    layout: manifest.layout,
    totalPixels: source.width * source.height,
    visiblePixelsBefore: countVisiblePixels(source),
    visiblePixelsAfter: 0,
    totalCandidatePixels: 0,
    totalHighSaturationCandidatePixels: 0,
    totalCleanedPixels: 0,
    totalClearedPixels: 0,
    totalFadedPixels: 0,
    preservedCandidatePixels: 0,
    preservedVisiblePixels: 0,
    frames: [],
    algorithm: {
      mode: "per-frame flood fill plus 2-pass edge expansion",
      transparentAlpha,
      edgeExpansionPasses,
    },
  };

  for (const frame of frames) {
    cleanFrame(source.data, cleaned.data, source.width, source.height, frame, report);
  }

  report.visiblePixelsAfter = countVisiblePixels(cleaned);

  writePng(outputPath, cleaned);
  writePng(path.join(qaDir, "before-after-contact-sheet.png"), makeBeforeAfterContactSheet(source, cleaned, frames, report));
  writePng(path.join(qaDir, "problem-frame-crops.png"), makeProblemFrameCrops(source, cleaned, frames, report));
  writeFileSync(path.join(qaDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");

  console.log(
    `Cleaned qversion spritesheet: cleaned=${report.totalCleanedPixels} cleared=${report.totalClearedPixels} faded=${report.totalFadedPixels}`,
  );
  console.log(`Output: ${outputPath}`);
  console.log(`QA: ${qaDir}`);
}

main();
