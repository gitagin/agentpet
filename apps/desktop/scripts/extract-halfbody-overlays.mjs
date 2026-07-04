import { deflateSync, inflateSync } from "node:zlib";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.resolve(__dirname, "..", "..", "..");

const halfbodyDir = path.join(root, "apps", "desktop", "public", "sprite-pet", "halfbody");
const workDir = path.join(halfbodyDir, "work");
const blinkDir = path.join(halfbodyDir, "blink");
const visemeDir = path.join(halfbodyDir, "viseme");
const previewDir = path.join(root, "output", "halfbody-overlays");

const basePath = path.join(halfbodyDir, "base.png");
const sourcePaths = {
  baseFull: path.join(workDir, "base_full.png"),
  blinkClosed: path.join(workDir, "blink_closed_full.png"),
  visemeAI: path.join(workDir, "viseme_AI_full.png"),
  visemeO: path.join(workDir, "viseme_O_full.png"),
};

const overlayTargets = {
  blinkClosed: path.join(blinkDir, "closed.png"),
  blinkHalf: path.join(blinkDir, "half.png"),
  blinkOpen: path.join(blinkDir, "open.png"),
  visemeAI: path.join(visemeDir, "AI.png"),
  visemeO: path.join(visemeDir, "O.png"),
  visemeClosed: path.join(visemeDir, "closed.png"),
  visemeE: path.join(visemeDir, "E.png"),
  visemeMBP: path.join(visemeDir, "MBP.png"),
  visemeFV: path.join(visemeDir, "FV.png"),
  visemeSmile: path.join(visemeDir, "smile.png"),
};

const transparentPlaceholders = [
  ["blink/open.png", overlayTargets.blinkOpen],
  ["viseme/closed.png", overlayTargets.visemeClosed],
  ["viseme/E.png", overlayTargets.visemeE],
  ["viseme/MBP.png", overlayTargets.visemeMBP],
  ["viseme/FV.png", overlayTargets.visemeFV],
  ["viseme/smile.png", overlayTargets.visemeSmile],
];

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
  for (let i = 0; i < buffer.length; i += 1) {
    c = crcTable[(c ^ buffer[i]) & 0xff] ^ (c >>> 8);
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

  return { filePath, width, height, mode: colorType === 6 ? "RGBA" : "RGB", data: rgba };
}

function writePng(filePath, image, options = {}) {
  const colorType = options.colorType ?? 6;
  if (colorType !== 2 && colorType !== 6) {
    throw new Error(`Unsupported output PNG color type: ${colorType}`);
  }
  const channels = colorType === 6 ? 4 : 3;
  mkdirSync(path.dirname(filePath), { recursive: true });
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(image.width, 0);
  ihdr.writeUInt32BE(image.height, 4);
  ihdr[8] = 8;
  ihdr[9] = colorType;
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  const stride = image.width * channels;
  const raw = Buffer.alloc((stride + 1) * image.height);
  for (let y = 0; y < image.height; y += 1) {
    const rowStart = y * (stride + 1);
    raw[rowStart] = 0;
    if (channels === 4) {
      Buffer.from(image.data.buffer, image.data.byteOffset + y * image.width * 4, image.width * 4).copy(
        raw,
        rowStart + 1,
      );
    } else {
      for (let x = 0; x < image.width; x += 1) {
        const src = (y * image.width + x) * 4;
        const dst = rowStart + 1 + x * 3;
        raw[dst] = image.data[src];
        raw[dst + 1] = image.data[src + 1];
        raw[dst + 2] = image.data[src + 2];
      }
    }
  }

  const png = Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND"),
  ]);
  writeFileSync(filePath, png);
}

function blankImage(width, height) {
  return { width, height, mode: "RGBA", data: new Uint8Array(width * height * 4) };
}

function cloneImage(image) {
  return { width: image.width, height: image.height, mode: "RGBA", data: new Uint8Array(image.data) };
}

function safePadWorkImageToBase(label, image, base, filePath) {
  if (image.width === base.width && image.height === base.height) {
    console.log(
      `safe_pad=${label} status=not_needed source_size=${image.width}x${image.height} target_size=${base.width}x${base.height}`,
    );
    return image;
  }

  const missingWidth = base.width - image.width;
  const missingHeight = base.height - image.height;
  if (image.width > base.width || image.height !== base.height || missingWidth > 8 || missingHeight !== 0) {
    throw new Error(
      `Cannot safe-pad ${label}: source=${image.width}x${image.height}, base=${base.width}x${base.height}. ` +
        "Only small right-edge width padding with equal height is allowed.",
    );
  }

  const repaired = cloneImage(base);
  paste(repaired, image, 0, 0);
  writePng(filePath, repaired, { colorType: 2 });
  console.log(
    `safe_pad=${label} status=written source_size=${image.width}x${image.height} ` +
      `target_size=${repaired.width}x${repaired.height} anchor=0,0 ` +
      `method=base_canvas_plus_top_left_paste resample=false scale=false path=${filePath}`,
  );
  return repaired;
}

function assertSameSize(images) {
  const [firstName, first] = images[0];
  const mismatches = [];
  for (const [name, image] of images) {
    if (image.width !== first.width || image.height !== first.height) {
      mismatches.push(`${name}=${image.width}x${image.height}, expected ${firstName}=${first.width}x${first.height}`);
    }
  }

  if (mismatches.length > 0) {
    console.error("dimension_check=false");
    console.error("dimension_mismatch_detected=true");
    for (const [name, image] of images) {
      console.error(`${name}: size=${image.width}x${image.height} mode=${image.mode}`);
    }
    throw new Error(`Image dimensions do not match; refusing to stretch or pad. ${mismatches.join("; ")}`);
  }

  console.log("dimension_check=true");
  for (const [name, image] of images) {
    console.log(`${name}: size=${image.width}x${image.height} mode=${image.mode}`);
  }
}

function luminance(r, g, b) {
  return 0.299 * r + 0.587 * g + 0.114 * b;
}

function saturation(r, g, b) {
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  return max === 0 ? 0 : (max - min) / max;
}

function isSkinLike(r, g, b) {
  const lum = luminance(r, g, b);
  return r > 112 && g > 68 && b > 56 && r > g + 14 && r > b + 24 && g > b - 10 && lum > 105 && lum < 230;
}

function setMaskPixel(mask, width, height, x, y, value) {
  if (x >= 0 && x < width && y >= 0 && y < height) {
    const index = y * width + x;
    if (value > mask[index]) {
      mask[index] = value;
    }
  }
}

function drawPolygon(mask, width, height, points, value = 1) {
  const minY = Math.max(0, Math.floor(Math.min(...points.map((p) => p[1]))));
  const maxY = Math.min(height - 1, Math.ceil(Math.max(...points.map((p) => p[1]))));
  for (let y = minY; y <= maxY; y += 1) {
    const intersections = [];
    for (let i = 0; i < points.length; i += 1) {
      const a = points[i];
      const b = points[(i + 1) % points.length];
      if ((a[1] <= y && b[1] > y) || (b[1] <= y && a[1] > y)) {
        intersections.push(a[0] + ((y - a[1]) * (b[0] - a[0])) / (b[1] - a[1]));
      }
    }
    intersections.sort((a, b) => a - b);
    for (let i = 0; i < intersections.length; i += 2) {
      const xStart = Math.max(0, Math.floor(intersections[i]));
      const xEnd = Math.min(width - 1, Math.ceil(intersections[i + 1]));
      for (let x = xStart; x <= xEnd; x += 1) {
        setMaskPixel(mask, width, height, x, y, value);
      }
    }
  }
}

function drawRotatedEllipse(mask, width, height, cx, cy, rx, ry, angleDegrees, value = 1) {
  const angle = (angleDegrees * Math.PI) / 180;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  const radius = Math.ceil(Math.max(rx, ry) + 4);
  for (let y = Math.max(0, Math.floor(cy - radius)); y <= Math.min(height - 1, Math.ceil(cy + radius)); y += 1) {
    for (let x = Math.max(0, Math.floor(cx - radius)); x <= Math.min(width - 1, Math.ceil(cx + radius)); x += 1) {
      const dx = x - cx;
      const dy = y - cy;
      const localX = dx * cos + dy * sin;
      const localY = -dx * sin + dy * cos;
      if ((localX * localX) / (rx * rx) + (localY * localY) / (ry * ry) <= 1) {
        setMaskPixel(mask, width, height, x, y, value);
      }
    }
  }
}

function boxBlur(mask, width, height, radius) {
  if (radius <= 0) {
    return mask;
  }
  let src = mask;
  let dst = new Float32Array(mask.length);
  const diameter = radius * 2 + 1;

  for (let y = 0; y < height; y += 1) {
    let sum = 0;
    for (let x = -radius; x <= radius; x += 1) {
      const sx = Math.min(width - 1, Math.max(0, x));
      sum += src[y * width + sx];
    }
    for (let x = 0; x < width; x += 1) {
      dst[y * width + x] = sum / diameter;
      const removeX = Math.max(0, x - radius);
      const addX = Math.min(width - 1, x + radius + 1);
      sum += src[y * width + addX] - src[y * width + removeX];
    }
  }

  src = dst;
  dst = new Float32Array(mask.length);
  for (let x = 0; x < width; x += 1) {
    let sum = 0;
    for (let y = -radius; y <= radius; y += 1) {
      const sy = Math.min(height - 1, Math.max(0, y));
      sum += src[sy * width + x];
    }
    for (let y = 0; y < height; y += 1) {
      dst[y * width + x] = sum / diameter;
      const removeY = Math.max(0, y - radius);
      const addY = Math.min(height - 1, y + radius + 1);
      sum += src[addY * width + x] - src[removeY * width + x];
    }
  }
  return dst;
}

function makeEyeMask(width, height) {
  const mask = new Float32Array(width * height);
  drawPolygon(mask, width, height, [
    [610, 385],
    [636, 373],
    [675, 382],
    [705, 397],
    [696, 415],
    [653, 422],
    [615, 410],
  ]);
  drawPolygon(mask, width, height, [
    [721, 345],
    [752, 333],
    [804, 339],
    [837, 354],
    [828, 378],
    [782, 390],
    [736, 373],
  ]);
  return boxBlur(mask, width, height, 1);
}

function dilateMask(mask, width, height, radius) {
  if (radius <= 0) {
    return mask;
  }
  const out = new Float32Array(mask.length);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      let value = 0;
      for (let dy = -radius; dy <= radius; dy += 1) {
        const sampleY = y + dy;
        if (sampleY < 0 || sampleY >= height) {
          continue;
        }
        for (let dx = -radius; dx <= radius; dx += 1) {
          const sampleX = x + dx;
          if (sampleX < 0 || sampleX >= width || dx * dx + dy * dy > radius * radius) {
            continue;
          }
          value = Math.max(value, mask[sampleY * width + sampleX]);
        }
      }
      out[y * width + x] = value;
    }
  }
  return out;
}

function makeEyeCoverMask(base, source) {
  const { width, height } = base;
  const rough = new Float32Array(width * height);
  drawPolygon(rough, width, height, [
    [618, 386],
    [638, 379],
    [674, 385],
    [700, 398],
    [692, 413],
    [654, 419],
    [622, 408],
  ]);
  drawPolygon(rough, width, height, [
    [730, 347],
    [756, 339],
    [798, 344],
    [827, 356],
    [818, 374],
    [781, 385],
    [740, 369],
  ]);

  const mask = new Float32Array(width * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const pixelIndex = y * width + x;
      if (rough[pixelIndex] <= 0) {
        continue;
      }

      const offset = pixelIndex * 4;
      const br = base.data[offset];
      const bg = base.data[offset + 1];
      const bb = base.data[offset + 2];
      const sr = source.data[offset];
      const sg = source.data[offset + 1];
      const sb = source.data[offset + 2];
      const diff = Math.max(Math.abs(sr - br), Math.abs(sg - bg), Math.abs(sb - bb));
      const baseLum = luminance(br, bg, bb);
      const sourceLum = luminance(sr, sg, sb);
      const basePinkEye = br > 100 && bb > 80 && br > bg + 22 && bb > bg + 8 && saturation(br, bg, bb) > 0.18;
      const baseEyeDark = baseLum < 120 && sourceLum > baseLum + 16 && saturation(br, bg, bb) > 0.08;
      const sourceEyelidSkin = isSkinLike(sr, sg, sb) && sourceLum > 100 && sourceLum < 205;

      if (sourceEyelidSkin && diff >= 9 && (basePinkEye || baseEyeDark)) {
        mask[pixelIndex] = rough[pixelIndex];
      }
    }
  }

  return boxBlur(boxBlur(dilateMask(mask, width, height, 5), width, height, 2), width, height, 1);
}

function makeMouthMask(width, height) {
  const mask = new Float32Array(width * height);
  drawRotatedEllipse(mask, width, height, 736, 448, 43, 22, -7);
  return boxBlur(boxBlur(mask, width, height, 2), width, height, 1);
}

function makeMouthCoverMask(width, height) {
  const mask = new Float32Array(width * height);
  drawRotatedEllipse(mask, width, height, 736, 448, 35, 11, -7);
  return boxBlur(boxBlur(mask, width, height, 2), width, height, 1);
}

function clampByte(value) {
  return Math.max(0, Math.min(255, Math.round(value)));
}

function findMaskBbox(mask, width, height, threshold = 0.001, padding = 0) {
  let minX = width;
  let minY = height;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (mask[y * width + x] > threshold) {
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x + 1);
        maxY = Math.max(maxY, y + 1);
      }
    }
  }

  if (maxX < 0) {
    return null;
  }
  return [
    Math.max(0, minX - padding),
    Math.max(0, minY - padding),
    Math.min(width, maxX + padding),
    Math.min(height, maxY + padding),
  ];
}

function sampleBaseSkinColor(base, mask, x, y, options) {
  const { radius, step } = options;
  for (const searchRadius of [radius, radius + 14, radius + 28]) {
    let totalWeight = 0;
    let red = 0;
    let green = 0;
    let blue = 0;
    for (let dy = -searchRadius; dy <= searchRadius; dy += step) {
      const sampleY = y + dy;
      if (sampleY < 0 || sampleY >= base.height) {
        continue;
      }
      for (let dx = -searchRadius; dx <= searchRadius; dx += step) {
        const sampleX = x + dx;
        if (sampleX < 0 || sampleX >= base.width || (dx === 0 && dy === 0)) {
          continue;
        }
        const distance2 = dx * dx + dy * dy;
        if (distance2 > searchRadius * searchRadius) {
          continue;
        }

        const maskIndex = sampleY * base.width + sampleX;
        if (mask[maskIndex] > 0.06) {
          continue;
        }

        const offset = maskIndex * 4;
        const r = base.data[offset];
        const g = base.data[offset + 1];
        const b = base.data[offset + 2];
        if (!isSkinLike(r, g, b)) {
          continue;
        }

        const weight = 1 / (1 + distance2);
        red += r * weight;
        green += g * weight;
        blue += b * weight;
        totalWeight += weight;
      }
    }

    if (totalWeight > 0) {
      return [clampByte(red / totalWeight), clampByte(green / totalWeight), clampByte(blue / totalWeight)];
    }
  }

  const offset = (y * base.width + x) * 4;
  return [base.data[offset], base.data[offset + 1], base.data[offset + 2]];
}

function makeBaseCoverLayer(base, mask, options) {
  const out = blankImage(base.width, base.height);
  const bbox = findMaskBbox(mask, base.width, base.height, 0.001, options.radius + 28);
  if (!bbox) {
    return out;
  }

  const [left, top, right, bottom] = bbox;
  for (let y = top; y < bottom; y += 1) {
    for (let x = left; x < right; x += 1) {
      const pixelIndex = y * base.width + x;
      const maskValue = mask[pixelIndex];
      if (maskValue <= 0.001) {
        continue;
      }

      const [r, g, b] = sampleBaseSkinColor(base, mask, x, y, options);
      const offset = pixelIndex * 4;
      out.data[offset] = r;
      out.data[offset + 1] = g;
      out.data[offset + 2] = b;
      out.data[offset + 3] = clampByte(maskValue * options.alpha);
    }
  }
  return out;
}

function smoothCoverLayer(layer, iterations = 2) {
  let current = cloneImage(layer);
  for (let pass = 0; pass < iterations; pass += 1) {
    const next = cloneImage(current);
    for (let y = 0; y < current.height; y += 1) {
      for (let x = 0; x < current.width; x += 1) {
        const offset = (y * current.width + x) * 4;
        if (current.data[offset + 3] <= 0) {
          continue;
        }

        let total = 0;
        let red = 0;
        let green = 0;
        let blue = 0;
        for (let dy = -2; dy <= 2; dy += 1) {
          const sampleY = y + dy;
          if (sampleY < 0 || sampleY >= current.height) {
            continue;
          }
          for (let dx = -2; dx <= 2; dx += 1) {
            const sampleX = x + dx;
            if (sampleX < 0 || sampleX >= current.width) {
              continue;
            }
            const sampleOffset = (sampleY * current.width + sampleX) * 4;
            const alpha = current.data[sampleOffset + 3] / 255;
            if (alpha <= 0) {
              continue;
            }
            const distance2 = dx * dx + dy * dy;
            const weight = alpha / (1 + distance2);
            red += current.data[sampleOffset] * weight;
            green += current.data[sampleOffset + 1] * weight;
            blue += current.data[sampleOffset + 2] * weight;
            total += weight;
          }
        }

        if (total > 0) {
          next.data[offset] = clampByte(red / total);
          next.data[offset + 1] = clampByte(green / total);
          next.data[offset + 2] = clampByte(blue / total);
        }
      }
    }
    current = next;
  }
  return current;
}

function diffuseCoverLayer(base, layer, mask, iterations = 80) {
  const bbox = findMaskBbox(mask, base.width, base.height, 0.001, 3);
  if (!bbox) {
    return layer;
  }

  let current = cloneImage(layer);
  const [left, top, right, bottom] = bbox;
  for (let pass = 0; pass < iterations; pass += 1) {
    const next = cloneImage(current);
    for (let y = top; y < bottom; y += 1) {
      for (let x = left; x < right; x += 1) {
        const pixelIndex = y * base.width + x;
        if (mask[pixelIndex] <= 0.001) {
          continue;
        }

        let total = 0;
        let red = 0;
        let green = 0;
        let blue = 0;
        for (const [dx, dy, weight] of [
          [0, -1, 1],
          [-1, 0, 1],
          [1, 0, 1],
          [0, 1, 1],
          [-1, -1, 0.7],
          [1, -1, 0.7],
          [-1, 1, 0.7],
          [1, 1, 0.7],
        ]) {
          const sampleX = x + dx;
          const sampleY = y + dy;
          if (sampleX < 0 || sampleX >= base.width || sampleY < 0 || sampleY >= base.height) {
            continue;
          }
          const sampleIndex = sampleY * base.width + sampleX;
          const sampleOffset = sampleIndex * 4;
          const source = mask[sampleIndex] > 0.001 ? current : base;
          red += source.data[sampleOffset] * weight;
          green += source.data[sampleOffset + 1] * weight;
          blue += source.data[sampleOffset + 2] * weight;
          total += weight;
        }

        if (total > 0) {
          const offset = pixelIndex * 4;
          next.data[offset] = clampByte(red / total);
          next.data[offset + 1] = clampByte(green / total);
          next.data[offset + 2] = clampByte(blue / total);
        }
      }
    }
    current = next;
  }
  return current;
}

function extractLineOverlay(base, source, mask, kind) {
  const out = blankImage(base.width, base.height);
  const width = base.width;
  const height = base.height;

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const pixelIndex = y * width + x;
      const maskValue = mask[pixelIndex];
      if (maskValue <= 0.001) {
        continue;
      }

      const offset = pixelIndex * 4;
      const br = base.data[offset];
      const bg = base.data[offset + 1];
      const bb = base.data[offset + 2];
      const sr = source.data[offset];
      const sg = source.data[offset + 1];
      const sb = source.data[offset + 2];

      const diffR = Math.abs(sr - br);
      const diffG = Math.abs(sg - bg);
      const diffB = Math.abs(sb - bb);
      const diff = Math.max(diffR, diffG, diffB);
      if (diff < 7) {
        continue;
      }

      const srcLum = luminance(sr, sg, sb);
      const baseLum = luminance(br, bg, bb);
      const sat = saturation(sr, sg, sb);
      const skinLike = isSkinLike(sr, sg, sb);
      let alpha = 0;

      if (kind === "eye") {
        const darkLine = srcLum < 92 && diff >= 8;
        const darkLash = srcLum < 125 && baseLum - srcLum > 18 && diff >= 12 && sat > 0.08;
        const softShadow = srcLum < 145 && baseLum - srcLum > 30 && diff >= 18 && !skinLike;
        if (darkLine) {
          alpha = 245 + Math.min(10, diff * 0.2);
        } else if (darkLash) {
          alpha = 190 + Math.min(65, diff * 1.2);
        } else if (softShadow) {
          alpha = 80 + Math.min(80, diff * 1.1);
        }
      } else if (kind === "mouth") {
        const darkMouth = !skinLike && srcLum < 128 && diff >= 10 && (baseLum - srcLum > 8 || sat > 0.16);
        const lipEdge = srcLum < 168 && diff >= 18 && sat > 0.2 && sr > sg + 24 && sr > sb + 18;
        const toothOrHighlight = srcLum > 172 && diff >= 34 && sat < 0.22 && !skinLike;
        if (darkMouth) {
          alpha = 235 + Math.min(20, diff * 0.4);
        } else if (lipEdge) {
          alpha = 165 + Math.min(80, diff * 1.1);
        } else if (toothOrHighlight) {
          alpha = 70 + Math.min(110, diff * 1.1);
        }
      }

      if (alpha <= 0) {
        continue;
      }

      const finalAlpha = clampByte(alpha * Math.min(1, maskValue));
      if (finalAlpha <= 0) {
        continue;
      }

      out.data[offset] = sr;
      out.data[offset + 1] = sg;
      out.data[offset + 2] = sb;
      out.data[offset + 3] = finalAlpha;
    }
  }

  return out;
}

function scaleAlpha(image, factor) {
  const out = cloneImage(image);
  for (let i = 3; i < out.data.length; i += 4) {
    out.data[i] = clampByte(out.data[i] * factor);
  }
  return out;
}

function composite(base, overlay) {
  const out = cloneImage(base);
  for (let i = 0; i < out.data.length; i += 4) {
    const alpha = overlay.data[i + 3] / 255;
    if (alpha <= 0) {
      out.data[i + 3] = 255;
      continue;
    }
    out.data[i] = clampByte(overlay.data[i] * alpha + out.data[i] * (1 - alpha));
    out.data[i + 1] = clampByte(overlay.data[i + 1] * alpha + out.data[i + 1] * (1 - alpha));
    out.data[i + 2] = clampByte(overlay.data[i + 2] * alpha + out.data[i + 2] * (1 - alpha));
    out.data[i + 3] = 255;
  }
  return out;
}

function compositeOverlayLayers(...layers) {
  if (layers.length === 0) {
    throw new Error("At least one layer is required.");
  }

  const out = blankImage(layers[0].width, layers[0].height);
  for (const layer of layers) {
    if (layer.width !== out.width || layer.height !== out.height) {
      throw new Error("Cannot composite overlay layers with different dimensions.");
    }

    for (let i = 0; i < out.data.length; i += 4) {
      const topAlpha = layer.data[i + 3] / 255;
      if (topAlpha <= 0) {
        continue;
      }

      const bottomAlpha = out.data[i + 3] / 255;
      const finalAlpha = topAlpha + bottomAlpha * (1 - topAlpha);
      if (finalAlpha <= 0) {
        continue;
      }

      out.data[i] = clampByte(
        (layer.data[i] * topAlpha + out.data[i] * bottomAlpha * (1 - topAlpha)) / finalAlpha,
      );
      out.data[i + 1] = clampByte(
        (layer.data[i + 1] * topAlpha + out.data[i + 1] * bottomAlpha * (1 - topAlpha)) / finalAlpha,
      );
      out.data[i + 2] = clampByte(
        (layer.data[i + 2] * topAlpha + out.data[i + 2] * bottomAlpha * (1 - topAlpha)) / finalAlpha,
      );
      out.data[i + 3] = clampByte(finalAlpha * 255);
    }
  }
  return out;
}

function crop(image, box) {
  const [left, top, right, bottom] = box;
  const width = right - left;
  const height = bottom - top;
  const out = blankImage(width, height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const src = ((top + y) * image.width + (left + x)) * 4;
      const dst = (y * width + x) * 4;
      out.data[dst] = image.data[src];
      out.data[dst + 1] = image.data[src + 1];
      out.data[dst + 2] = image.data[src + 2];
      out.data[dst + 3] = image.data[src + 3];
    }
  }
  return out;
}

function paste(target, source, left, top) {
  for (let y = 0; y < source.height; y += 1) {
    for (let x = 0; x < source.width; x += 1) {
      const dstX = left + x;
      const dstY = top + y;
      if (dstX < 0 || dstY < 0 || dstX >= target.width || dstY >= target.height) {
        continue;
      }
      const src = (y * source.width + x) * 4;
      const dst = (dstY * target.width + dstX) * 4;
      target.data[dst] = source.data[src];
      target.data[dst + 1] = source.data[src + 1];
      target.data[dst + 2] = source.data[src + 2];
      target.data[dst + 3] = source.data[src + 3];
    }
  }
}

function alphaStats(image) {
  let minX = image.width;
  let minY = image.height;
  let maxX = -1;
  let maxY = -1;
  let pixels = 0;
  for (let y = 0; y < image.height; y += 1) {
    for (let x = 0; x < image.width; x += 1) {
      const alpha = image.data[(y * image.width + x) * 4 + 3];
      if (alpha > 0) {
        pixels += 1;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x + 1);
        maxY = Math.max(maxY, y + 1);
      }
    }
  }
  return {
    bbox: pixels > 0 ? [minX, minY, maxX, maxY] : null,
    pixels,
  };
}

function makeContactSheet(crops) {
  const gap = 12;
  const width = crops.reduce((sum, item) => sum + item.width, 0) + gap * (crops.length + 1);
  const height = Math.max(...crops.map((item) => item.height)) + gap * 2;
  const sheet = blankImage(width, height);
  for (let i = 0; i < sheet.data.length; i += 4) {
    sheet.data[i] = 18;
    sheet.data[i + 1] = 18;
    sheet.data[i + 2] = 22;
    sheet.data[i + 3] = 255;
  }
  let x = gap;
  for (const item of crops) {
    paste(sheet, item, x, gap);
    x += item.width + gap;
  }
  return sheet;
}

function saveOverlay(label, filePath, image, summaries) {
  writePng(filePath, image);
  const stats = alphaStats(image);
  const summary = {
    label,
    filePath,
    size: `${image.width}x${image.height}`,
    mode: "RGBA",
    alphaBBox: stats.bbox,
    alphaPixels: stats.pixels,
  };
  summaries.push(summary);
  console.log(
    `${label}: path=${filePath} size=${summary.size} mode=RGBA alpha_bbox=${JSON.stringify(
      summary.alphaBBox,
    )} alpha_pixels=${summary.alphaPixels}`,
  );
}

function savePreview(label, base, overlay, cropBox, previewSummaries) {
  const merged = composite(base, overlay);
  const compositePath = path.join(previewDir, `${label}_composite.png`);
  const cropPath = path.join(previewDir, `${label}_crop.png`);
  const cropped = crop(merged, cropBox);
  writePng(compositePath, merged);
  writePng(cropPath, cropped);
  previewSummaries.push(compositePath, cropPath);
  return cropped;
}

function main() {
  mkdirSync(blinkDir, { recursive: true });
  mkdirSync(visemeDir, { recursive: true });
  mkdirSync(previewDir, { recursive: true });

  const base = readPng(basePath);
  const baseFull = readPng(sourcePaths.baseFull);
  let blinkClosedFull = readPng(sourcePaths.blinkClosed);
  const visemeAIFull = readPng(sourcePaths.visemeAI);
  let visemeOFull = readPng(sourcePaths.visemeO);

  blinkClosedFull = safePadWorkImageToBase(
    "work/blink_closed_full.png",
    blinkClosedFull,
    base,
    sourcePaths.blinkClosed,
  );
  visemeOFull = safePadWorkImageToBase("work/viseme_O_full.png", visemeOFull, base, sourcePaths.visemeO);

  assertSameSize([
    ["base.png", base],
    ["work/base_full.png", baseFull],
    ["work/blink_closed_full.png", blinkClosedFull],
    ["work/viseme_AI_full.png", visemeAIFull],
    ["work/viseme_O_full.png", visemeOFull],
  ]);

  const overlaySummaries = [];
  const previewSummaries = [];
  const placeholders = [];

  const empty = blankImage(base.width, base.height);
  for (const [label, target] of transparentPlaceholders) {
    saveOverlay(label, target, empty, overlaySummaries);
    placeholders.push(label);
  }

  const eyeFeatureMask = makeEyeMask(base.width, base.height);
  const eyeCoverMask = makeEyeCoverMask(base, blinkClosedFull);
  const mouthFeatureMask = makeMouthMask(base.width, base.height);
  const mouthCoverMask = makeMouthCoverMask(base.width, base.height);

  const blinkCover = diffuseCoverLayer(
    base,
    smoothCoverLayer(makeBaseCoverLayer(base, eyeCoverMask, { alpha: 252, radius: 28, step: 2 }), 2),
    eyeCoverMask,
    90,
  );
  const mouthCover = diffuseCoverLayer(
    base,
    smoothCoverLayer(makeBaseCoverLayer(base, mouthCoverMask, { alpha: 246, radius: 20, step: 2 }), 1),
    mouthCoverMask,
    42,
  );
  const blinkFeature = extractLineOverlay(base, blinkClosedFull, eyeFeatureMask, "eye");
  const visemeAIFeature = extractLineOverlay(base, visemeAIFull, mouthFeatureMask, "mouth");
  const visemeOFeature = extractLineOverlay(base, visemeOFull, mouthFeatureMask, "mouth");

  const blinkClosed = compositeOverlayLayers(blinkCover, blinkFeature);
  const blinkHalf = scaleAlpha(blinkClosed, 0.55);
  const visemeAI = compositeOverlayLayers(mouthCover, visemeAIFeature);
  const visemeO = compositeOverlayLayers(mouthCover, visemeOFeature);

  for (const [label, layer] of [
    ["cover/blink_closed", blinkCover],
    ["feature/blink_closed", blinkFeature],
    ["cover/mouth", mouthCover],
    ["feature/viseme_AI", visemeAIFeature],
    ["feature/viseme_O", visemeOFeature],
  ]) {
    const stats = alphaStats(layer);
    console.log(`${label}: alpha_bbox=${JSON.stringify(stats.bbox)} alpha_pixels=${stats.pixels}`);
  }

  saveOverlay("blink/closed.png", overlayTargets.blinkClosed, blinkClosed, overlaySummaries);
  saveOverlay("blink/half.png", overlayTargets.blinkHalf, blinkHalf, overlaySummaries);
  saveOverlay("viseme/AI.png", overlayTargets.visemeAI, visemeAI, overlaySummaries);
  saveOverlay("viseme/O.png", overlayTargets.visemeO, visemeO, overlaySummaries);

  const blinkCrop = savePreview("blink_closed", base, blinkClosed, [560, 285, 890, 470], previewSummaries);
  const aiCrop = savePreview("viseme_AI", base, visemeAI, [665, 405, 805, 500], previewSummaries);
  const oCrop = savePreview("viseme_O", base, visemeO, [665, 405, 805, 500], previewSummaries);
  const contactSheetPath = path.join(previewDir, "contact_sheet.png");
  writePng(contactSheetPath, makeContactSheet([blinkCrop, aiCrop, oCrop]));
  previewSummaries.push(contactSheetPath);

  console.log(`transparent_placeholders=${placeholders.join(", ")}`);
  console.log("preview_files:");
  for (const item of previewSummaries) {
    console.log(`- ${item}`);
  }
}

try {
  main();
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`error=${message}`);
  process.exitCode = 1;
}
