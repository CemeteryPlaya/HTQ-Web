import sharp from "sharp";
import fs from "fs";
import path from "path";

// ── Configuration ──────────────────────────────────────────────────────────
const IMG_DIR = "public/images";
const LOGO_DIR = "public/logos";

// Responsive size presets by image category
const SIZE_PRESETS = {
  hero:       [640, 1024, 1600],
  panels:     [400, 800],
  directions: [320, 536],
};

// Detect category from filename
function getPreset(name) {
  if (name.startsWith("hero"))           return SIZE_PRESETS.hero;
  if (name.startsWith("panels"))         return SIZE_PRESETS.panels;
  if (name.startsWith("directionsLogo")) return SIZE_PRESETS.directions;
  return null; // logo and others — no responsive variants
}

// ── Step 1: Convert PNG/JPEG sources → WebP (existing behavior) ───────────
const sources = fs.readdirSync(IMG_DIR).filter(f => /\.(png|jpeg|jpg)$/i.test(f));

for (const f of sources) {
  const inp = path.join(IMG_DIR, f);
  const out = path.join(IMG_DIR, f.replace(/\.(png|jpeg|jpg)$/i, ".webp"));
  const before = fs.statSync(inp).size;
  await sharp(inp).webp({ quality: 80 }).toFile(out);
  const after = fs.statSync(out).size;
  const pct = Math.round((1 - after / before) * 100);
  console.log(`[webp] ${f} ${kb(before)} -> ${kb(after)} (-${pct}%)`);
}

// ── Step 2: Generate AVIF for ALL WebP images ─────────────────────────────
const webpFiles = fs.readdirSync(IMG_DIR).filter(f => /\.webp$/i.test(f));

console.log("\n--- Generating AVIF variants ---");
for (const f of webpFiles) {
  const inp = path.join(IMG_DIR, f);
  const out = path.join(IMG_DIR, f.replace(/\.webp$/i, ".avif"));

  // Skip if AVIF already exists and is newer than source
  if (fs.existsSync(out) && fs.statSync(out).mtimeMs >= fs.statSync(inp).mtimeMs) {
    console.log(`[avif] ${f} — skipped (up to date)`);
    continue;
  }

  const before = fs.statSync(inp).size;
  await sharp(inp).avif({ quality: 80 }).toFile(out);
  const after = fs.statSync(out).size;
  const pct = Math.round((1 - after / before) * 100);
  console.log(`[avif] ${f} -> ${path.basename(out)} ${kb(before)} -> ${kb(after)} (-${pct}%)`);
}

// ── Step 3: Generate responsive size variants (WebP + AVIF) ───────────────
console.log("\n--- Generating responsive variants ---");
for (const f of webpFiles) {
  const name = f.replace(/\.webp$/i, "");
  const preset = getPreset(name);
  if (!preset) continue;

  const inp = path.join(IMG_DIR, f);
  const meta = await sharp(inp).metadata();
  const origWidth = meta.width;

  for (const width of preset) {
    // Skip if variant would be >= original width (the original serves as the largest)
    if (width >= origWidth) continue;

    const height = Math.round((width / origWidth) * meta.height);

    // WebP variant
    const webpOut = path.join(IMG_DIR, `${name}-${width}w.webp`);
    if (!fs.existsSync(webpOut)) {
      await sharp(inp).resize(width, height).webp({ quality: 80 }).toFile(webpOut);
      console.log(`[responsive] ${path.basename(webpOut)} ${width}x${height} (${kb(fs.statSync(webpOut).size)})`);
    }

    // AVIF variant
    const avifOut = path.join(IMG_DIR, `${name}-${width}w.avif`);
    if (!fs.existsSync(avifOut)) {
      await sharp(inp).resize(width, height).avif({ quality: 80 }).toFile(avifOut);
      console.log(`[responsive] ${path.basename(avifOut)} ${width}x${height} (${kb(fs.statSync(avifOut).size)})`);
    }
  }
}

// ── Step 4: Check SVG logos for embedded base64 ───────────────────────────
console.log("\n--- SVG logos ---");
const svgs = fs.readdirSync(LOGO_DIR).filter(f => f.endsWith(".svg"));
for (const f of svgs) {
  const fp = path.join(LOGO_DIR, f);
  const content = fs.readFileSync(fp, "utf8");
  const size = kb(fs.statSync(fp).size);
  console.log(`${f} ${size} base64: ${content.includes("base64")}`);
}

console.log("\nDone!");

// ── Helpers ───────────────────────────────────────────────────────────────
function kb(bytes) {
  return Math.round(bytes / 1024) + "KB";
}
