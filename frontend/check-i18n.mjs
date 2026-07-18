import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const localesDir = path.join(__dirname, 'public', 'locales');
const srcDir = path.join(__dirname, 'src');

function flattenObject(ob) {
    var toReturn = {};
    for (var i in ob) {
        if (!ob.hasOwnProperty(i)) continue;
        if ((typeof ob[i]) == 'object' && ob[i] !== null) {
            var flatObject = flattenObject(ob[i]);
            for (var x in flatObject) {
                if (!flatObject.hasOwnProperty(x)) continue;
                toReturn[i + '.' + x] = flatObject[x];
            }
        } else {
            toReturn[i] = ob[i];
        }
    }
    return toReturn;
}

const ruJson = JSON.parse(fs.readFileSync(path.join(localesDir, 'ru', 'translation.json'), 'utf8'));
const enJson = JSON.parse(fs.readFileSync(path.join(localesDir, 'en', 'translation.json'), 'utf8'));

const ruKeys = flattenObject(ruJson);
const enKeys = flattenObject(enJson);

function walk(dir, fileList = []) {
    const files = fs.readdirSync(dir);
    for (const file of files) {
        const filePath = path.join(dir, file);
        if (filePath.includes('node_modules')) continue;
        const stat = fs.statSync(filePath);
        if (stat.isDirectory()) {
            fileList = walk(filePath, fileList);
        } else if (/\.(tsx|ts|jsx|js)$/.test(filePath)) {
            fileList.push(filePath);
        }
    }
    return fileList;
}

const allFiles = walk(srcDir);
const usedKeys = new Set();
const keyFiles = {};

const regexes = [
    /t\(\s*['"]([^'"]+)['"]/g,
    /i18nKey\s*=\s*['"]([^'"]+)['"]/g
];

for (const file of allFiles) {
    const content = fs.readFileSync(file, 'utf8');
    for (const regex of regexes) {
        let match;
        while ((match = regex.exec(content)) !== null) {
            const k = match[1];
            usedKeys.add(k);
            if (!keyFiles[k]) keyFiles[k] = new Set();
            keyFiles[k].add(file.replace(__dirname, ''));
        }
    }
}

console.log(`Found ${usedKeys.size} unique keys in source code.`);

const missingInRu = [];
const missingInEn = [];

for (const key of usedKeys) {
    if (key.includes('${') || key.includes('{{')) continue;

    if (ruKeys[key] === undefined) {
        missingInRu.push({ key, files: Array.from(keyFiles[key]) });
    }
    if (enKeys[key] === undefined) {
        missingInEn.push({ key, files: Array.from(keyFiles[key]) });
    }
}

console.log(`Missing in RU: ${missingInRu.length}`);
if (missingInRu.length > 0) {
    missingInRu.forEach(m => console.log(`- ${m.key} (in ${m.files.join(', ')})`));
}

console.log(`\nMissing in EN: ${missingInEn.length}`);
if (missingInEn.length > 0) {
    missingInEn.forEach(m => console.log(`- ${m.key} (in ${m.files.join(', ')})`));
}
