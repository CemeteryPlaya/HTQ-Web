import fs from 'fs';
import path from 'path';
import sharp from 'sharp';

const logoDir = 'public/logos';
const svgs = ['huaweiLogo.svg', 'risenLogo.svg', 'sepcoLogo.svg', 'tbeaLogo.svg', 'trinaSolarLogo.svg', 'unitedGreenLogo.svg'];

(async () => {
    for (const f of svgs) {
        const fp = path.join(logoDir, f);
        if (!fs.existsSync(fp)) continue;

        const content = fs.readFileSync(fp, 'utf8');
        const match = content.match(/data:image\/(png|jpeg);base64,([A-Za-z0-9+/=]+)/);

        if (match) {
            const base64Data = match[2];
            const buffer = Buffer.from(base64Data, 'base64');
            const outName = f.replace('.svg', '.webp');
            const outPath = path.join(logoDir, outName);

            await sharp(buffer).webp({ quality: 80 }).toFile(outPath);
            const newSize = fs.statSync(outPath).size;
            const oldSize = fs.statSync(fp).size;

            console.log(`Extracted: ${outName} (${Math.round(oldSize / 1024)}KB -> ${Math.round(newSize / 1024)}KB WEBP)`);

            // Delete the bloated SVG file and any intermediate PNG/JPEG
            fs.unlinkSync(fp);
            const pngPath = fp.replace('.svg', '.png');
            if (fs.existsSync(pngPath)) {
                fs.unlinkSync(pngPath);
            }
        }
    }
    console.log('✅ Done extracting and cleaning up SVG logos!');
})();
