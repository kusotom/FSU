#!/usr/bin/env node
/**
 * Offline checksum verification for FSU raw JSONL logs.
 *
 * SAFETY:
 * - Does not open sockets.
 * - Does not send UDP.
 * - Reads local JSONL only.
 */
const fs = require("fs");
const path = require("path");
const { parseFsuFrame, findHexCandidate } = require("../app/modules/fsu_gateway/parser/fsu-frame-v03-utils");

function ymd() {
  return new Date().toISOString().slice(0, 10);
}

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

function inc(obj, key, n = 1) {
  obj[key] = (obj[key] || 0) + n;
}

function frameClassOf(parsed, entry) {
  if (entry.frameClass) return entry.frameClass;
  const channel = entry.channel || entry.type || entry.kind || entry.source || "UNKNOWN";
  let prefix = String(channel).includes("RDS") ? "RDS" : (String(channel).includes("DSC") ? "DSC" : "FSU");
  const len = parsed.totalLength;
  const type = parsed.typeA ? parsed.typeA.toUpperCase() : "UNKNOWN";
  if (prefix === "DSC" && (len === 209 || len === 245)) return `DSC_CONFIG_${len}_TYPE_${type}`;
  if (prefix === "DSC" && len === 24) return `DSC_SHORT_24_TYPE_${type}`;
  if (prefix === "RDS" && len === 30) return `RDS_SHORT_30_TYPE_${type}`;
  return `${prefix}_LEN_${len}_TYPE_${type}`;
}

const args = parseArgs(process.argv);
const input = args.input || findLatestRawLog();
if (!input) {
  console.error("No input JSONL found. Use --input backend/logs/fsu_raw_packets/YYYY-MM-DD.jsonl");
  process.exit(2);
}
if (!fs.existsSync(input)) {
  console.error(`Input not found: ${input}`);
  process.exit(2);
}

const outDate = args.outDate || path.basename(input, ".jsonl").match(/^\d{4}-\d{2}-\d{2}$/)?.[0] || ymd();
const outDir = path.join(process.cwd(), "backend/logs/fsu_raw_packets");
fs.mkdirSync(outDir, { recursive: true });

const stats = {};
let totalLines = 0;
let parsedLines = 0;
let skipped = 0;
const samples = {};

const lines = fs.readFileSync(input, "utf8").split(/\r?\n/);
for (const line of lines) {
  if (!line.trim()) continue;
  totalLines += 1;
  let entry;
  try { entry = JSON.parse(line); } catch { skipped += 1; continue; }

  if (args.deviceIp) {
    const s = JSON.stringify(entry);
    if (!s.includes(args.deviceIp)) continue;
  }

  const hex = findHexCandidate(entry);
  if (!hex) { skipped += 1; continue; }

  const p = parseFsuFrame(hex);
  if (!p.ok) { skipped += 1; continue; }

  parsedLines += 1;
  const cls = frameClassOf(p, entry);
  if (!stats[cls]) {
    stats[cls] = {
      frameClass: cls,
      count: 0,
      validLE: 0,
      validBE: 0,
      invalid: 0,
      payloadLengthOk: 0,
      ackRequired: 0,
      typeBytesSummary: p.typeBytesSummary,
      classByteHex: p.classByte == null ? null : `0x${p.classByte.toString(16).padStart(2, "0")}`,
      firstSample: null
    };
  }
  const st = stats[cls];
  st.count += 1;
  if (p.checksumValidLE) st.validLE += 1;
  if (p.checksumValidBE) st.validBE += 1;
  if (!p.checksumValid) st.invalid += 1;
  if (p.payloadLengthMatchesTotalMinus24) st.payloadLengthOk += 1;
  if (p.ackRequiredFlag) st.ackRequired += 1;
  if (!st.firstSample) {
    st.firstSample = {
      totalLength: p.totalLength,
      magicHex: p.magicHex,
      typeA: p.typeA,
      typeBytesSummary: p.typeBytesSummary,
      seqLE: p.seqLE,
      payloadLengthLE: p.payloadLengthLE,
      checksumStoredHex: p.checksumStoredHex,
      checksumCalculatedHex: p.checksumCalculatedHex,
      checksumValid: p.checksumValid,
      checksumEndianGuess: p.checksumEndianGuess
    };
  }
}

const rows = Object.values(stats).sort((a, b) => b.count - a.count);
const jsonOut = {
  input,
  generatedAt: new Date().toISOString(),
  totalLines,
  parsedLines,
  skipped,
  safety: { udpSent: false, socketOpened: false, ackSent: false },
  stats: rows
};

const jsonPath = path.join(outDir, `checksum-verification-${outDate}.json`);
fs.writeFileSync(jsonPath, JSON.stringify(jsonOut, null, 2));

let md = `# FSU checksum verification ${outDate}\n\n`;
md += `Input: \`${input}\`\n\n`;
md += `Safety: offline only; no UDP sent; no ACK sent.\n\n`;
md += `Total lines: ${totalLines}\n\nParsed packets: ${parsedLines}\n\nSkipped: ${skipped}\n\n`;
md += `| frameClass | count | validLE | validBE | invalid | payloadLengthOk | ackRequired | typeBytes | classByte |\n`;
md += `|---|---:|---:|---:|---:|---:|---:|---|---|\n`;
for (const r of rows) {
  md += `| ${r.frameClass} | ${r.count} | ${r.validLE} | ${r.validBE} | ${r.invalid} | ${r.payloadLengthOk} | ${r.ackRequired} | ${r.typeBytesSummary} | ${r.classByteHex || ""} |\n`;
}
md += `\n## Samples\n\n`;
for (const r of rows.slice(0, 20)) {
  md += `### ${r.frameClass}\n\n\`\`\`json\n${JSON.stringify(r.firstSample, null, 2)}\n\`\`\`\n\n`;
}
const mdPath = path.join(outDir, `checksum-verification-${outDate}.md`);
fs.writeFileSync(mdPath, md);
console.log(`Wrote ${mdPath}`);
console.log(`Wrote ${jsonPath}`);
