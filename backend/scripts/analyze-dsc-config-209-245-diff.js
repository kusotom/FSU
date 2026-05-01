#!/usr/bin/env node
/**
 * Offline DSC_CONFIG 209/245 diff analyzer.
 *
 * SAFETY:
 * - Does not open sockets.
 * - Does not send UDP.
 * - Reads local JSONL only.
 */
const fs = require("fs");
const path = require("path");
const { parseFsuFrame, findHexCandidate } = require("../app/modules/fsu_gateway/parser/fsu-frame-v03-utils");

function findLatestRawLog() {
  const dir = path.join(process.cwd(), "backend/logs/fsu_raw_packets");
  if (!fs.existsSync(dir)) return null;
  const files = fs.readdirSync(dir)
    .filter(f => /^\d{4}-\d{2}-\d{2}\.jsonl$/.test(f))
    .map(f => path.join(dir, f))
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
  return files[0] || null;
}

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    if (argv[i] === "--input" || argv[i] === "-i") args.input = argv[++i];
    else if (argv[i] === "--out-date") args.outDate = argv[++i];
    else if (argv[i] === "--device-ip") args.deviceIp = argv[++i];
  }
  return args;
}

function longestCommonPrefix(a, b) {
  const n = Math.min(a.length, b.length);
  let i = 0;
  while (i < n && a[i] === b[i]) i += 1;
  return i;
}

function offsetDiff(a, b, limit = 256) {
  const n = Math.min(Math.max(a.length, b.length), limit);
  const rows = [];
  for (let i = 0; i < n; i += 1) {
    const av = i < a.length ? a[i] : null;
    const bv = i < b.length ? b[i] : null;
    if (av !== bv) rows.push({
      offset: i,
      a: av == null ? null : av.toString(16).padStart(2, "0"),
      b: bv == null ? null : bv.toString(16).padStart(2, "0")
    });
  }
  return rows;
}

function asciiSpans(buf) {
  const out = [];
  let start = null, s = "";
  for (let i = 0; i < buf.length; i += 1) {
    const c = buf[i];
    if (c >= 0x20 && c <= 0x7e) {
      if (start == null) start = i;
      s += String.fromCharCode(c);
    } else {
      if (start != null && s.length >= 4) out.push({ offset: start, text: s });
      start = null; s = "";
    }
  }
  if (start != null && s.length >= 4) out.push({ offset: start, text: s });
  return out;
}

const args = parseArgs(process.argv);
const input = args.input || findLatestRawLog();
if (!input || !fs.existsSync(input)) {
  console.error("Input JSONL not found. Use --input backend/logs/fsu_raw_packets/YYYY-MM-DD.jsonl");
  process.exit(2);
}
const outDate = args.outDate || path.basename(input, ".jsonl").match(/^\d{4}-\d{2}-\d{2}$/)?.[0] || new Date().toISOString().slice(0,10);
const outDir = path.join(process.cwd(), "backend/logs/fsu_raw_packets");
fs.mkdirSync(outDir, { recursive: true });

const frames209 = [];
const frames245 = [];
let total = 0;

for (const line of fs.readFileSync(input, "utf8").split(/\r?\n/)) {
  if (!line.trim()) continue;
  let entry; try { entry = JSON.parse(line); } catch { continue; }
  if (args.deviceIp) {
    const s = JSON.stringify(entry);
    if (!s.includes(args.deviceIp)) continue;
  }
  const hex = findHexCandidate(entry);
  if (!hex) continue;
  const p = parseFsuFrame(hex);
  if (!p.ok) continue;
  if (p.typeBytesSummary.toLowerCase() === "110046ff" && p.totalLength === 209) frames209.push({ parsed: p, hex });
  if (p.typeBytesSummary.toLowerCase() === "110046ff" && p.totalLength === 245) frames245.push({ parsed: p, hex });
  total += 1;
}

const a = frames209[0]?.parsed ? Buffer.from(frames209[0].hex, "hex").slice(24) : Buffer.alloc(0);
const b = frames245[0]?.parsed ? Buffer.from(frames245[0].hex, "hex").slice(24) : Buffer.alloc(0);
const lcp = a.length && b.length ? longestCommonPrefix(a, b) : 0;
const extra245 = b.length > a.length ? b.slice(a.length) : Buffer.alloc(0);

const result = {
  input,
  generatedAt: new Date().toISOString(),
  safety: { udpSent: false, socketOpened: false },
  counts: { allParsed: total, dscConfig209: frames209.length, dscConfig245: frames245.length },
  sample209: frames209[0]?.parsed || null,
  sample245: frames245[0]?.parsed || null,
  bodyComparison: {
    body209Length: a.length,
    body245Length: b.length,
    longestCommonPrefixBytes: lcp,
    extra245LengthIfBasePlusExt: extra245.length,
    extra245HexIfBasePlusExt: extra245.toString("hex"),
    firstDiffs: offsetDiff(a, b, 120),
    ascii209: asciiSpans(a).slice(0, 50),
    ascii245: asciiSpans(b).slice(0, 50),
    asciiExtra245: asciiSpans(extra245)
  }
};

const jsonPath = path.join(outDir, `dsc-config-209-245-diff-${outDate}.json`);
fs.writeFileSync(jsonPath, JSON.stringify(result, null, 2));

let md = `# DSC CONFIG 209/245 diff ${outDate}\n\n`;
md += `Input: \`${input}\`\n\nSafety: offline only; no UDP sent.\n\n`;
md += `Parsed packets: ${total}\n\n209 frames: ${frames209.length}\n\n245 frames: ${frames245.length}\n\n`;
md += `Body 209 length: ${a.length}\n\nBody 245 length: ${b.length}\n\n`;
md += `Longest common prefix: ${lcp} bytes\n\n`;
md += `Extra 245 bytes if 245 = 209 + extension: ${extra245.length}\n\n`;
md += `Extra 245 hex:\n\n\`\`\`text\n${extra245.toString("hex") || "(none)"}\n\`\`\`\n\n`;
md += `## First body diffs\n\n| offset | 209 | 245 |\n|---:|---|---|\n`;
for (const d of result.bodyComparison.firstDiffs.slice(0, 120)) {
  md += `| ${d.offset} | ${d.a ?? ""} | ${d.b ?? ""} |\n`;
}
md += `\n## ASCII spans 209\n\n\`\`\`json\n${JSON.stringify(result.bodyComparison.ascii209, null, 2)}\n\`\`\`\n\n`;
md += `## ASCII spans 245\n\n\`\`\`json\n${JSON.stringify(result.bodyComparison.ascii245, null, 2)}\n\`\`\`\n\n`;
const mdPath = path.join(outDir, `dsc-config-209-245-diff-${outDate}.md`);
fs.writeFileSync(mdPath, md);
console.log(`Wrote ${mdPath}`);
console.log(`Wrote ${jsonPath}`);
