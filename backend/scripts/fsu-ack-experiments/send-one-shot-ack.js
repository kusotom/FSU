#!/usr/bin/env node
// EXPERIMENTAL ONLY - Do not run in production.
// Requires explicit manual approval before any packet send.
// These tools must not be wired into fsu-gateway automatic replies.
"use strict";

const dgram = require("dgram");
const fs = require("fs");
const path = require("path");

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

function cleanHex(value) {
  return String(value || "").replace(/[^0-9a-f]/gi, "").toLowerCase();
}

function dateStem(date = new Date()) {
  return date.toISOString().slice(0, 10);
}

function usage() {
  return [
    "usage:",
    "  node backend/scripts/fsu-ack-experiments/send-one-shot-ack.js --target-host 192.168.100.100 --target-port 6002 --ack-hex <hex> --label <label> --yes-i-know-this-is-experimental",
    "",
    "This script sends exactly one UDP packet only when all required arguments are present.",
  ].join("\n");
}

function validate(args) {
  const missing = [];
  for (const key of ["target-host", "target-port", "ack-hex", "label"]) {
    if (!args[key]) {
      missing.push(`--${key}`);
    }
  }
  if (!args["yes-i-know-this-is-experimental"]) {
    missing.push("--yes-i-know-this-is-experimental");
  }
  if (missing.length) {
    return `missing required argument(s): ${missing.join(", ")}`;
  }

  const port = Number(args["target-port"]);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    return "--target-port must be an integer in 1..65535";
  }

  const hex = cleanHex(args["ack-hex"]);
  if (!hex || hex.length % 2 !== 0) {
    return "--ack-hex must contain an even number of hex digits";
  }

  return null;
}

function logPathForNow() {
  return path.join(
    __dirname,
    "..",
    "..",
    "logs",
    "fsu_raw_packets",
    `ack-experiment-${dateStem()}.jsonl`,
  );
}

function appendExperimentLog(record) {
  const logPath = logPathForNow();
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  fs.appendFileSync(logPath, `${JSON.stringify(record)}\n`, "utf8");
  return logPath;
}

async function sendOne({ targetHost, targetPort, ackHex, label }) {
  const socket = dgram.createSocket("udp4");
  const payload = Buffer.from(ackHex, "hex");
  await new Promise((resolve, reject) => {
    socket.send(payload, targetPort, targetHost, (error) => {
      socket.close();
      if (error) {
        reject(error);
        return;
      }
      resolve();
    });
  });

  const record = {
    sentAt: new Date().toISOString(),
    targetHost,
    targetPort,
    label,
    ackHex,
    byteLength: payload.length,
    warnings: [
      "experimental one-shot UDP send",
      "ACK format is not confirmed",
      "not part of fsu-gateway runtime",
      "do not repeat automatically",
    ],
  };
  const logPath = appendExperimentLog(record);
  return { record, logPath };
}

async function main() {
  const args = parseArgs(process.argv);
  const error = validate(args);
  if (error) {
    console.error(error);
    console.error(usage());
    process.exit(1);
  }

  const targetHost = args["target-host"];
  const targetPort = Number(args["target-port"]);
  const ackHex = cleanHex(args["ack-hex"]);
  const label = args.label;
  const byteLength = ackHex.length / 2;

  console.log("About to send one experimental UDP packet:");
  console.log(JSON.stringify({ targetHost, targetPort, ackHex, byteLength, label }, null, 2));

  const { logPath } = await sendOne({ targetHost, targetPort, ackHex, label });
  console.log(`sent one packet; log: ${logPath}`);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.stack || error.message);
    process.exit(1);
  });
}


