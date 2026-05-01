#!/usr/bin/env node
// EXPERIMENTAL ONLY - Do not run in production.
// Requires explicit manual approval before any packet send.
// These tools must not be wired into fsu-gateway automatic replies.
"use strict";

const fs = require("fs");
const path = require("path");

const RAW_LOG_RE = /^\d{4}-\d{2}-\d{2}\.jsonl$/;
const DEFAULT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_raw_packets");

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

function dateKeyFromName(name) {
  const match = String(name).match(/^(\d{4}-\d{2}-\d{2})\.jsonl$/);
  return match ? match[1] : "";
}

function listRawLogs(dir = DEFAULT_DIR) {
  if (!fs.existsSync(dir)) throw new Error(`raw packet log directory not found: ${dir}`);
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .filter((entry) => entry.isFile() && RAW_LOG_RE.test(entry.name))
    .map((entry) => {
      const fullPath = path.join(dir, entry.name);
      const stat = fs.statSync(fullPath);
      return {
        path: fullPath,
        name: entry.name,
        date: dateKeyFromName(entry.name),
        mtime: stat.mtime.toISOString(),
        mtimeMs: stat.mtimeMs,
        size: stat.size,
      };
    })
    .sort((a, b) => b.date.localeCompare(a.date) || b.mtimeMs - a.mtimeMs);
}

function selectLatestRawLog(dir = DEFAULT_DIR) {
  const availableRawLogs = listRawLogs(dir);
  if (!availableRawLogs.length) throw new Error(`no raw packet logs found in ${dir}`);
  const latest = availableRawLogs[0];
  return {
    latestRawLog: latest.path,
    reason: "selected latest raw packet log by YYYY-MM-DD filename, then mtime",
    availableRawLogs,
  };
}

function main() {
  const args = parseArgs(process.argv);
  const result = selectLatestRawLog(path.resolve(args.dir || DEFAULT_DIR));
  console.log(JSON.stringify(result, null, 2));
}

module.exports = { RAW_LOG_RE, DEFAULT_DIR, listRawLogs, selectLatestRawLog };

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}


