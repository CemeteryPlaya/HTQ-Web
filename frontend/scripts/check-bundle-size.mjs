// scripts/check-bundle-size.mjs
// Performance budget enforcement — fails CI/CD if limits exceeded
import { readdirSync, statSync } from 'fs';
import { join } from 'path';

const BUDGET = {
    totalAssets: 10 * 1024 * 1024,  // 10 MB — total dist/assets
    singleChunk: 1024 * 1024,       // 1 MB — any single JS chunk (parsed)
    totalJS: 5 * 1024 * 1024,       // 5 MB — total JS
};

function getFileSizes(dir) {
    const results = { js: 0, css: 0, total: 0, files: [] };
    for (const file of readdirSync(dir)) {
        const p = join(dir, file);
        const stat = statSync(p);
        if (!stat.isFile()) continue;
        results.total += stat.size;
        if (file.endsWith('.js')) {
            results.js += stat.size;
            results.files.push({ name: file, size: stat.size });
            if (stat.size > BUDGET.singleChunk) {
                console.error(`  ❌ CHUNK TOO LARGE: ${file} = ${(stat.size / 1024).toFixed(0)} KB (limit: ${BUDGET.singleChunk / 1024} KB)`);
                process.exitCode = 1;
            }
        }
        if (file.endsWith('.css')) {
            results.css += stat.size;
        }
    }
    return results;
}

const assetsDir = join(process.cwd(), 'dist', 'assets');
const r = getFileSizes(assetsDir);

console.log('\n📊 Bundle Size Report:');
console.log(`  JS total:     ${(r.js / 1024).toFixed(0)} KB (budget: ${(BUDGET.totalJS / 1024).toFixed(0)} KB)`);
console.log(`  CSS total:    ${(r.css / 1024).toFixed(0)} KB`);
console.log(`  Assets total: ${(r.total / 1024).toFixed(0)} KB (budget: ${(BUDGET.totalAssets / 1024).toFixed(0)} KB)`);
console.log('\n  JS Chunks:');
r.files.sort((a, b) => b.size - a.size).forEach(f => {
    const kb = (f.size / 1024).toFixed(0);
    const flag = f.size > BUDGET.singleChunk ? ' ⚠️' : ' ✅';
    console.log(`    ${flag} ${f.name}: ${kb} KB`);
});

if (r.js > BUDGET.totalJS) {
    console.error(`\n  ❌ TOTAL JS BUDGET EXCEEDED: ${(r.js / 1024).toFixed(0)} KB > ${(BUDGET.totalJS / 1024).toFixed(0)} KB`);
    process.exitCode = 1;
}
if (r.total > BUDGET.totalAssets) {
    console.error(`\n  ❌ TOTAL ASSETS BUDGET EXCEEDED: ${(r.total / 1024).toFixed(0)} KB > ${(BUDGET.totalAssets / 1024).toFixed(0)} KB`);
    process.exitCode = 1;
}

if (!process.exitCode) {
    console.log('\n  ✅ All performance budgets passed!\n');
}
