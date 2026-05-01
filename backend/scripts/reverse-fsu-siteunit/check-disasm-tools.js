#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const DATE_STEM = "2026-04-28";
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");

const COMMAND_TOOLS = [
  "arm-linux-gnueabi-objdump",
  "arm-none-eabi-objdump",
  "llvm-objdump",
  "objdump",
  "readelf",
  "llvm-readelf",
];

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

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    windowsHide: true,
    timeout: options.timeout || 10000,
  });
  return {
    command,
    args,
    status: result.status,
    error: result.error ? result.error.message : null,
    stdout: (result.stdout || "").trim(),
    stderr: (result.stderr || "").trim(),
  };
}

function detectCommandTool(name) {
  const result = run(name, ["--version"]);
  return {
    name,
    available: !result.error && result.status === 0,
    version: result.stdout.split(/\r?\n/)[0] || result.stderr.split(/\r?\n/)[0] || null,
    error: result.error,
  };
}

function detectPythonCapstone() {
  const result = run("python", [
    "-c",
    "import capstone; print(capstone.__version__)",
  ]);
  return {
    name: "python capstone",
    available: !result.error && result.status === 0,
    version: result.stdout || null,
    error: result.error || (result.status === 0 ? null : result.stderr || "python import failed"),
  };
}

function detectNpmPackage(packageName) {
  const result = run("node", [
    "-e",
    `try { const p=require(${JSON.stringify(packageName)}); console.log(p.version || 'installed'); } catch (e) { process.exit(1); }`,
  ]);
  return {
    name: `npm ${packageName}`,
    available: !result.error && result.status === 0,
    version: result.stdout || null,
    error: result.error || (result.status === 0 ? null : result.stderr || "not installed"),
  };
}

function writeReport(outDir, report) {
  fs.mkdirSync(outDir, { recursive: true });
  const mdPath = path.join(outDir, `disasm-tools-${DATE_STEM}.md`);
  const rows = report.tools
    .map((tool) => `| ${tool.name} | ${tool.available ? "yes" : "no"} | ${tool.version || ""} | ${tool.error || ""} |`)
    .join("\n");
  const md = [
    "# Disassembly Tool Check",
    "",
    `Generated: ${report.generatedAt}`,
    "",
    "| Tool | Available | Version | Error |",
    "| --- | --- | --- | --- |",
    rows,
    "",
    "## Selected Tool",
    "",
    report.selectedTool
      ? `Use ${report.selectedTool.name}.`
      : "No disassembler was found. Existing static scripts can still produce string/xref reports, but ARM instruction recovery requires installing GNU binutils for ARM, LLVM tools, or Python capstone.",
    "",
    "## Install Suggestions",
    "",
    "- Preferred: install an ARM binutils package that provides `arm-linux-gnueabi-objdump` or `arm-none-eabi-objdump`.",
    "- Alternative: install LLVM tools providing `llvm-objdump` and `llvm-readelf`.",
    "- Python fallback: `python -m pip install --user capstone pyelftools`.",
    "",
  ].join("\n");
  fs.writeFileSync(mdPath, md, "utf8");
  return mdPath;
}

function main() {
  const args = parseArgs(process.argv);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const tools = [
    ...COMMAND_TOOLS.map(detectCommandTool),
    detectPythonCapstone(),
    detectNpmPackage("capstone"),
    detectNpmPackage("capstone-js"),
  ];
  const selectedTool =
    tools.find((tool) => tool.available && /objdump/.test(tool.name)) ||
    tools.find((tool) => tool.available && tool.name === "python capstone") ||
    null;
  const report = {
    generatedAt: new Date().toISOString(),
    tools,
    selectedTool,
  };
  const mdPath = writeReport(outDir, report);
  console.log(JSON.stringify({ ...report, mdPath }, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
