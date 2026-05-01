#!/usr/bin/env node
"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const DATE_STEM = "2026-04-28";
const DEFAULT_FIRMWARE_ROOT = path.join(process.env.USERPROFILE || process.cwd(), "Desktop", "FSU");
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");

const KEYWORDS = [
  "ACK",
  "LOGIN",
  "LOGIN_ACK",
  "Register",
  "Register OK",
  "LoginToDSC",
  "LogToDS",
  "ParseData",
  "fail SOI",
  "fail checksum",
  "fail length",
  "SendHeartbeat",
  "SendRealData",
  "SendEventData",
  "GetServiceAddr",
  "DS busy",
  "SOI",
  "checksum",
  "length",
  "recv",
  "recvfrom",
  "sendto",
  "socket",
  "timeout",
];

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) {
      continue;
    }
    const key = arg.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith("--")) {
      args[key] = next;
      i += 1;
    } else {
      args[key] = true;
    }
  }
  return args;
}

function walkFiles(root, basename, results = []) {
  if (!fs.existsSync(root)) {
    return results;
  }

  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const fullPath = path.join(root, entry.name);
    if (entry.isDirectory()) {
      walkFiles(fullPath, basename, results);
      continue;
    }
    if (entry.isFile() && entry.name === basename) {
      results.push(fullPath);
    }
  }
  return results;
}

function resolveSiteUnitPath(args) {
  if (args.siteunit) {
    return path.resolve(args.siteunit);
  }

  const firmwareRoot = path.resolve(args["firmware-root"] || DEFAULT_FIRMWARE_ROOT);
  const direct = path.join(firmwareRoot, "SiteUnit");
  if (fs.existsSync(direct)) {
    return direct;
  }

  const matches = walkFiles(firmwareRoot, "SiteUnit");
  if (matches.length === 1) {
    return matches[0];
  }
  if (matches.length > 1) {
    return matches.sort((a, b) => a.length - b.length || a.localeCompare(b))[0];
  }

  throw new Error(`SiteUnit not found under firmware root: ${firmwareRoot}`);
}

function isAsciiPrintable(byte) {
  return byte >= 0x20 && byte <= 0x7e;
}

function extractAsciiStrings(buffer, minLength = 4) {
  const strings = [];
  let start = -1;

  for (let i = 0; i <= buffer.length; i += 1) {
    const byte = i < buffer.length ? buffer[i] : 0;
    if (i < buffer.length && isAsciiPrintable(byte)) {
      if (start === -1) {
        start = i;
      }
      continue;
    }

    if (start !== -1) {
      const length = i - start;
      if (length >= minLength) {
        strings.push({
          fileOffset: start,
          fileOffsetHex: `0x${start.toString(16)}`,
          length,
          text: buffer.toString("ascii", start, i),
        });
      }
      start = -1;
    }
  }

  return strings;
}

function keywordMatches(strings) {
  const matches = [];
  for (const keyword of KEYWORDS) {
    const needle = keyword.toLowerCase();
    const hits = strings
      .filter((item) => item.text.toLowerCase().includes(needle))
      .map((item) => ({
        keyword,
        fileOffset: item.fileOffset,
        fileOffsetHex: item.fileOffsetHex,
        length: item.length,
        text: item.text,
      }));
    matches.push({ keyword, count: hits.length, hits });
  }
  return matches;
}

function nearbyKeywordStrings(strings, windowBytes = 512) {
  const keywordOffsets = new Set();
  for (const item of strings) {
    const lower = item.text.toLowerCase();
    if (KEYWORDS.some((keyword) => lower.includes(keyword.toLowerCase()))) {
      keywordOffsets.add(item.fileOffset);
    }
  }

  const nearby = [];
  for (const item of strings) {
    for (const offset of keywordOffsets) {
      if (Math.abs(item.fileOffset - offset) <= windowBytes) {
        nearby.push(item);
        break;
      }
    }
  }
  return nearby;
}

function markdownTable(rows, columns) {
  const header = `| ${columns.map((column) => column.title).join(" | ")} |`;
  const divider = `| ${columns.map(() => "---").join(" | ")} |`;
  const body = rows.map((row) => {
    const values = columns.map((column) => String(column.value(row)).replace(/\|/g, "\\|"));
    return `| ${values.join(" | ")} |`;
  });
  return [header, divider, ...body].join("\n");
}

function writeOutputs({ siteUnitPath, buffer, strings, matches, nearby, outDir }) {
  fs.mkdirSync(outDir, { recursive: true });

  const fileInfo = {
    path: siteUnitPath,
    size: buffer.length,
    sha256: crypto.createHash("sha256").update(buffer).digest("hex"),
  };
  const result = {
    generatedAt: new Date().toISOString(),
    fileInfo,
    minLength: 4,
    stringCount: strings.length,
    keywords: KEYWORDS,
    keywordMatches: matches,
    nearbyKeywordStrings: nearby,
    strings,
  };

  const jsonPath = path.join(outDir, `siteunit-strings-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");

  const keywordRows = matches.flatMap((group) =>
    group.hits.map((hit) => ({
      keyword: group.keyword,
      offset: hit.fileOffsetHex,
      length: hit.length,
      text: hit.text,
    })),
  );

  const md = [
    "# SiteUnit String Index",
    "",
    `Generated: ${result.generatedAt}`,
    `SiteUnit: ${fileInfo.path}`,
    `Size: ${fileInfo.size}`,
    `SHA256: ${fileInfo.sha256}`,
    `ASCII string count: ${strings.length}`,
    "",
    "## Keyword Matches",
    "",
    keywordRows.length
      ? markdownTable(keywordRows, [
          { title: "Keyword", value: (row) => row.keyword },
          { title: "Offset", value: (row) => row.offset },
          { title: "Length", value: (row) => row.length },
          { title: "Text", value: (row) => `\`${row.text}\`` },
        ])
      : "No keyword matches.",
    "",
    "## Strings Near Keyword Matches (+/- 512 bytes)",
    "",
    nearby.length
      ? markdownTable(nearby, [
          { title: "Offset", value: (row) => row.fileOffsetHex },
          { title: "Length", value: (row) => row.length },
          { title: "Text", value: (row) => `\`${row.text}\`` },
        ])
      : "No nearby strings.",
    "",
    "## Full ASCII String Index",
    "",
    markdownTable(strings, [
      { title: "Offset", value: (row) => row.fileOffsetHex },
      { title: "Length", value: (row) => row.length },
      { title: "Text", value: (row) => `\`${row.text}\`` },
    ]),
    "",
  ].join("\n");

  const mdPath = path.join(outDir, `siteunit-strings-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath, result };
}

function main() {
  const args = parseArgs(process.argv);
  const siteUnitPath = resolveSiteUnitPath(args);
  if (!fs.existsSync(siteUnitPath)) {
    throw new Error(`SiteUnit path does not exist: ${siteUnitPath}`);
  }

  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const buffer = fs.readFileSync(siteUnitPath);
  const strings = extractAsciiStrings(buffer, 4);
  const matches = keywordMatches(strings);
  const nearby = nearbyKeywordStrings(strings);
  const { jsonPath, mdPath, result } = writeOutputs({ siteUnitPath, buffer, strings, matches, nearby, outDir });

  console.log(
    JSON.stringify(
      {
        siteUnitPath,
        stringCount: result.stringCount,
        keywordMatchCount: matches.reduce((sum, group) => sum + group.count, 0),
        jsonPath,
        mdPath,
      },
      null,
      2,
    ),
  );
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
