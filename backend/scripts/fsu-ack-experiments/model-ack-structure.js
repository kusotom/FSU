#!/usr/bin/env node
// EXPERIMENTAL ONLY - Do not run in production.
// Requires explicit manual approval before any packet send.
// These tools must not be wired into fsu-gateway automatic replies.
"use strict";

const fs = require("fs");
const path = require("path");

const DATE_STEM = "2026-04-28";
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) continue;
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

function modelAckStructure(extra = {}) {
  return {
    status: "incomplete",
    reason: "ACK type/body/success code not confirmed",
    ackHex: null,
    confirmedFields: {
      soi: {
        offset: 0,
        hex: "6d7e",
      },
      lengthLE: {
        offset: 20,
        formula: "totalLength - 24",
      },
      checksumOffset: {
        offset: 22,
      },
      checksumLE: {
        offset: 22,
        formula: "uint16 sum(buffer[2..totalLen-1]) with checksum bytes zeroed",
        caveat: "Verified for DSC_CONFIG_209, DSC_CONFIG_245, and RDS_SHORT_30; DSC_SHORT_24 uses fixed -0x150 adjustment and is not an ACK model source.",
      },
      bodyOffset: {
        offset: 24,
        note: "ParseData passes frame + 0x18 to body handlers; earlier bodyOffset=22 views included checksum bytes.",
      },
    },
    candidateFields: {
      seqStrategy: ["mirror request seqLE", "request seqLE + 1", "independent platform seq"],
      typeA: [],
      body: [],
      successCode: [],
      ...(extra.candidateFields || {}),
    },
    unknowns: [
      "ACK typeA",
      "ACK body layout",
      "success code",
      "whether seq must mirror request",
      "whether response goes to DSC source port or declared URI port",
      "source of fp-0x135 localStatus from wire response",
      "wire response offset for internal success/fail/unregister status",
      ...(extra.unknowns || []),
    ],
    supplementalStage13: {
      localStatus: "fp-0x135",
      localStatusSourceCandidate: "one byte copied from pointer saved at fp-0x30 via call 0xca5c; original frame offset not confirmed",
      internalStatusValues: {
        success: 0,
        fail: 1,
        unregister: 2,
      },
      ctx129Writes: {
        success: "0x7e954 writes 0",
        fail: "0x7e99c writes 1",
        unregister: "0x7e9f8 writes 2",
      },
      caveat: "Internal status values are copied from an input pointer candidate, but the original wire offset, ACK typeA, and ACK body layout are not confirmed.",
      ...(extra.supplementalStage13 || {}),
    },
    doNotSend: true,
  };
}

function writeReports(outDir, model) {
  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `ack-structure-model-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(model, null, 2)}\n`, "utf8");

  const md = [
    "# ACK Structure Model",
    "",
    `Generated: ${model.generatedAt}`,
    "",
    "```json",
    JSON.stringify(model, null, 2),
    "```",
    "",
  ].join("\n");
  const mdPath = path.join(outDir, `ack-structure-model-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function main() {
  const args = parseArgs(process.argv);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const model = {
    generatedAt: new Date().toISOString(),
    ...modelAckStructure(),
  };
  const paths = writeReports(outDir, model);
  console.log(JSON.stringify(paths, null, 2));
}

module.exports = { modelAckStructure };

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}


