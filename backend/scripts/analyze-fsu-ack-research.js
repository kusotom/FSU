#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const DEFAULT_RAW_LOG = path.join(__dirname, "..", "logs", "fsu_raw_packets", "2026-04-28.jsonl");
const DEFAULT_FIRMWARE_ROOT = process.env.FSU_FIRMWARE_DIR || path.join(os.homedir(), "Desktop", "FSU");

const KEYWORDS = [
  "ACK",
  "ack",
  "Login",
  "LOGIN",
  "LoginToDSC",
  "Register",
  "Register OK",
  "RDS",
  "DSC",
  "RecvRdsData",
  "RecvDscData",
  "SendHeartbeat",
  "SendRealData",
  "SendEventData",
  "SendAllCommState",
  "SendRDSHeartbeat",
  "SendRDSRealDataQueue",
  "udp://",
  "6000",
  "6002",
  "6d7e",
  "d2ff",
  "46ff",
  "1f00",
  "1100",
  "1180",
  "recv",
  "recvfrom",
  "select",
  "poll",
  "socket",
  "bind",
  "connect",
  "sendto",
  "send",
  "Receive",
  "Recv",
  "timeout",
  "Login to Dsc timeout",
  "RunRDS",
];

const PATTERNS = [
  { name: "6d 7e", bytes: [0x6d, 0x7e] },
  { name: "1f 00 d2 ff", bytes: [0x1f, 0x00, 0xd2, 0xff] },
  { name: "11 00 46 ff", bytes: [0x11, 0x00, 0x46, 0xff] },
  { name: "11 80 d2 ff", bytes: [0x11, 0x80, 0xd2, 0xff] },
  { name: "d2 ff", bytes: [0xd2, 0xff] },
  { name: "46 ff", bytes: [0x46, 0xff] },
];

function parseDateStem(filePath) {
  const match = path.basename(filePath).match(/(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : new Date().toISOString().slice(0, 10);
}

function table(headers, rows) {
  const escapeCell = (value) => String(value ?? "").replace(/\r?\n/g, "<br>").replace(/\|/g, "\\|");
  return [
    `| ${headers.map(escapeCell).join(" | ")} |`,
    `| ${headers.map(() => "---").join(" | ")} |`,
    ...rows.map((row) => `| ${row.map(escapeCell).join(" | ")} |`),
    "",
  ].join("\n");
}

function commandAvailable(command) {
  const result = spawnSync("where.exe", [command], { encoding: "utf8" });
  return result.status === 0 ? result.stdout.trim().split(/\r?\n/).filter(Boolean) : [];
}

function listFilesRecursive(dir) {
  if (!fs.existsSync(dir)) {
    return [];
  }
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...listFilesRecursive(fullPath));
    } else if (entry.isFile()) {
      out.push(fullPath);
    }
  }
  return out;
}

function existingCandidateFiles(root) {
  const direct = [
    path.join(root, "home", "idu", "SiteUnit"),
    path.join(root, "home", "idu", "IduStart"),
    path.join(root, "home", "apache", "WebProvider.so"),
  ];
  const soFiles = listFilesRecursive(path.join(root, "home", "idu", "SO")).filter((file) =>
    /\.(so|ini)$/i.test(file) || path.basename(file).includes(".so"),
  );
  const iniFiles = listFilesRecursive(path.join(root, "home", "idu")).filter((file) => /\.ini$/i.test(file));
  const xmlFiles = listFilesRecursive(path.join(root, "home", "idu", "XmlCfg")).filter((file) => /\.xml$/i.test(file));
  return [...new Set([...direct, ...soFiles, ...iniFiles, ...xmlFiles])].filter((file) => fs.existsSync(file));
}

function extractAsciiStrings(buf, minLen = 4) {
  const strings = [];
  let start = -1;
  for (let i = 0; i <= buf.length; i += 1) {
    const byte = i < buf.length ? buf[i] : -1;
    const printable = byte >= 0x20 && byte <= 0x7e;
    if (printable && start < 0) {
      start = i;
    }
    if ((!printable || i === buf.length) && start >= 0) {
      if (i - start >= minLen) {
        strings.push({
          offset: start,
          text: buf.subarray(start, i).toString("ascii"),
        });
      }
      start = -1;
    }
  }
  return strings;
}

function indexOfPattern(buf, pattern, start) {
  for (let i = start; i <= buf.length - pattern.length; i += 1) {
    let matched = true;
    for (let j = 0; j < pattern.length; j += 1) {
      if (buf[i + j] !== pattern[j]) {
        matched = false;
        break;
      }
    }
    if (matched) {
      return i;
    }
  }
  return -1;
}

function findPatternHits(buf, patternBytes) {
  const offsets = [];
  let start = 0;
  while (start < buf.length) {
    const offset = indexOfPattern(buf, patternBytes, start);
    if (offset < 0) {
      break;
    }
    offsets.push(offset);
    start = offset + 1;
  }
  return offsets;
}

function hexDumpAround(buf, offset, radius = 64) {
  const start = Math.max(0, offset - radius);
  const end = Math.min(buf.length, offset + radius);
  return [...buf.subarray(start, end)].map((byte) => byte.toString(16).padStart(2, "0")).join(" ");
}

function nearbyStrings(buf, offset, radius = 256) {
  const start = Math.max(0, offset - radius);
  const end = Math.min(buf.length, offset + radius);
  return extractAsciiStrings(buf.subarray(start, end), 4)
    .map((item) => ({ offset: start + item.offset, text: item.text }))
    .slice(0, 12);
}

function keywordHits(strings) {
  const hits = {};
  for (const keyword of KEYWORDS) {
    const matches = strings.filter((item) => item.text.includes(keyword)).slice(0, 20);
    if (matches.length) {
      hits[keyword] = matches;
    }
  }
  return hits;
}

function analyzeFirmware(root) {
  const files = existingCandidateFiles(root);
  const fileAnalyses = [];
  const patternSummary = [];
  const keywordSummary = [];

  for (const file of files) {
    const buf = fs.readFileSync(file);
    const strings = extractAsciiStrings(buf);
    const keywords = keywordHits(strings);
    for (const [keyword, hits] of Object.entries(keywords)) {
      keywordSummary.push({
        file,
        keyword,
        countShown: hits.length,
        examples: hits.slice(0, 5),
      });
    }

    const patterns = {};
    for (const pattern of PATTERNS) {
      const offsets = findPatternHits(buf, pattern.bytes);
      patterns[pattern.name] = {
        count: offsets.length,
        hits: offsets.slice(0, 8).map((offset) => ({
          offset,
          offsetHex: `0x${offset.toString(16)}`,
          hexDump: hexDumpAround(buf, offset),
          nearbyStrings: nearbyStrings(buf, offset),
        })),
      };
      if (offsets.length) {
        patternSummary.push({
          file,
          pattern: pattern.name,
          count: offsets.length,
        });
      }
    }

    fileAnalyses.push({
      file,
      size: buf.length,
      stringCount: strings.length,
      keywords,
      patterns,
    });
  }

  return {
    root,
    files,
    commandAvailability: {
      strings: commandAvailable("strings"),
      objdump: commandAvailable("objdump"),
      readelf: commandAvailable("readelf"),
      file: commandAvailable("file"),
      r2: commandAvailable("r2"),
      radare2: commandAvailable("radare2"),
    },
    keywordSummary,
    patternSummary,
    fileAnalyses,
  };
}

function readJsonIfExists(filePath) {
  if (!fs.existsSync(filePath)) {
    return null;
  }
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function renderAckResearch({ rawLogPath, firmware, endpoint, outputPath }) {
  const lines = [];
  lines.push(`# FSU ACK / Handshake Research - ${parseDateStem(rawLogPath)}`);
  lines.push("");
  lines.push(`Raw log: \`${rawLogPath}\``);
  lines.push(`Firmware root: \`${firmware.root}\``);
  lines.push(`Generated at: \`${new Date().toISOString()}\``);
  lines.push("");

  lines.push("## 1. Current Device State Assessment");
  lines.push("");
  lines.push(
    "- The device continues to emit DSC/RDS short periodic/status-like frames and repeated DSC config URI frames.",
  );
  lines.push("- No new real-time data or alarm frame class has been observed in the current raw log.");
  lines.push("- This supports a conservative hypothesis that the device is waiting for a platform response, ACK, registration confirmation, or handshake transition.");
  lines.push("");

  lines.push("## 2. Endpoint Relationship");
  lines.push("");
  if (endpoint) {
    lines.push(table(["protocol:remotePort", "count"], Object.entries(endpoint.protocolRemotePortCounts)));
    lines.push(table(["long frame URI port", "count"], Object.entries(endpoint.longFrameUriPortCounts)));
    lines.push(table(["source vs URI port", "count"], Object.entries(endpoint.sourceVsUriPortCounts)));
    lines.push(
      table(
        ["metric", "value"],
        [
          ["likelyReplyTarget", endpoint.interpretation.likelyReplyTarget],
          ["rationale", endpoint.interpretation.rationale],
        ],
      ),
    );
  } else {
    lines.push("Endpoint analysis JSON was not found when this report was generated.");
    lines.push("");
  }

  lines.push("## 3. Firmware Scope And Tool Availability");
  lines.push("");
  lines.push(table(["file", "size"], firmware.files.map((file) => [file, fs.statSync(file).size])));
  lines.push(
    table(
      ["tool", "available paths"],
      Object.entries(firmware.commandAvailability).map(([tool, paths]) => [tool, paths.join("<br>") || "(not found)"]),
    ),
  );

  lines.push("## 4. Firmware String Clues");
  lines.push("");
  if (!firmware.keywordSummary.length) {
    lines.push("(no keyword string hits)");
    lines.push("");
  } else {
    lines.push(
      table(
        ["file", "keyword", "shown hits", "examples"],
        firmware.keywordSummary.map((row) => [
          row.file,
          row.keyword,
          row.countShown,
          row.examples.map((hit) => `${hit.offset}: ${hit.text}`).join("<br>"),
        ]),
      ),
    );
  }

  lines.push("## 5. Binary Pattern Hits");
  lines.push("");
  if (!firmware.patternSummary.length) {
    lines.push("(no binary pattern hits)");
    lines.push("");
  } else {
    lines.push(table(["file", "pattern", "count"], firmware.patternSummary.map((row) => [row.file, row.pattern, row.count])));
  }

  lines.push("## 6. Pattern Hit Contexts");
  lines.push("");
  for (const fileAnalysis of firmware.fileAnalyses) {
    const rows = [];
    for (const [pattern, result] of Object.entries(fileAnalysis.patterns)) {
      for (const hit of result.hits.slice(0, 4)) {
        rows.push([
          pattern,
          hit.offsetHex,
          hit.hexDump,
          hit.nearbyStrings.map((item) => `${item.offset}: ${item.text}`).join("<br>"),
        ]);
      }
    }
    if (!rows.length) {
      continue;
    }
    lines.push(`### ${fileAnalysis.file}`);
    lines.push("");
    lines.push(table(["pattern", "offset", "hex around +/-64", "nearby strings"], rows));
  }

  lines.push("## 7. Response Handling Clues");
  lines.push("");
  const responseKeywords = [
    "recv",
    "recvfrom",
    "select",
    "poll",
    "socket",
    "bind",
    "connect",
    "sendto",
    "Receive",
    "Recv",
    "timeout",
    "Register OK",
    "Login to Dsc timeout",
    "LoginToDSC",
    "RunRDS",
  ];
  const responseRows = firmware.keywordSummary
    .filter((row) => responseKeywords.includes(row.keyword))
    .map((row) => [row.file, row.keyword, row.examples.map((hit) => `${hit.offset}: ${hit.text}`).join("<br>")]);
  lines.push(responseRows.length ? table(["file", "keyword", "examples"], responseRows) : "(no response handling keyword hits)\n");

  lines.push("## 8. ACK Candidate Format Status");
  lines.push("");
  lines.push(
    table(
      ["field", "status"],
      [
        ["header 6d7e", "likely mirrored framing marker, but ACK frame class not confirmed"],
        ["seqLE", "likely important to mirror or reference request sequence, not confirmed"],
        ["typeA", "request type signatures are known; ACK type signature not confirmed"],
        ["payloadLength", "request length field is known; ACK payload length not confirmed"],
        ["checksum", "not confirmed"],
        ["ACK body", "not confirmed"],
      ],
    ),
  );

  lines.push("## 9. Possible ACK Target And Trigger Objects");
  lines.push("");
  lines.push("- Target port: source remotePort is the safer first hypothesis for UDP request/response, while declared URI ports remain research candidates.");
  lines.push("- Trigger objects to study offline: DSC_CONFIG_209, DSC_CONFIG_245, DSC_SHORT_24, RDS_SHORT_30.");
  lines.push("- Current evidence favors long config frames as the main handshake/registration transition blocker, but this is not confirmed.");
  lines.push("");

  lines.push("## 10. Controlled Experiment Suggestions");
  lines.push("");
  lines.push("- Do not send ACK from production gateway.");
  lines.push("- Build ACK candidates offline with `build-fsu-ack-candidates.js`; keep `ackHex=null` until ACK type/checksum evidence is found.");
  lines.push("- If a live test is approved later, isolate it behind a one-shot lab script and packet capture both directions.");
  lines.push("- Test source-port reply before declared URI port reply unless firmware evidence contradicts it.");
  lines.push("");

  fs.writeFileSync(outputPath, `${lines.join("\n")}\n`, "utf8");
}

function main() {
  const rawLogPath = path.resolve(process.argv[2] || DEFAULT_RAW_LOG);
  const firmwareRoot = path.resolve(process.argv[3] || DEFAULT_FIRMWARE_ROOT);
  const dateStem = parseDateStem(rawLogPath);
  const outputDir = path.dirname(rawLogPath);
  const outputPath = path.join(outputDir, `ack-research-${dateStem}.md`);
  const endpointJsonPath = path.join(outputDir, `endpoint-analysis-${dateStem}.json`);

  if (!fs.existsSync(firmwareRoot)) {
    console.error(`firmware root not found: ${firmwareRoot}`);
    process.exit(1);
  }

  const firmware = analyzeFirmware(firmwareRoot);
  const endpoint = readJsonIfExists(endpointJsonPath);
  renderAckResearch({ rawLogPath, firmware, endpoint, outputPath });
  console.log(`ack research: ${outputPath}`);
  console.log(`firmware root: ${firmwareRoot}`);
  console.log(`files analyzed: ${firmware.files.length}`);
}

main();
