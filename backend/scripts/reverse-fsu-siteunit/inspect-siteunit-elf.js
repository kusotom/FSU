#!/usr/bin/env node
"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const DATE_STEM = "2026-04-28";
const DEFAULT_FIRMWARE_ROOT = path.join(process.env.USERPROFILE || process.cwd(), "Desktop", "FSU");
const DEFAULT_OUT_DIR = path.join(process.cwd(), "backend", "logs", "fsu_reverse");

const VERIFY_OFFSETS = [0x6e878, 0x6d77c, 0x6f634];

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

function walkFiles(root, basename, results = []) {
  if (!fs.existsSync(root)) return results;
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const fullPath = path.join(root, entry.name);
    if (entry.isDirectory()) walkFiles(fullPath, basename, results);
    else if (entry.isFile() && entry.name === basename) results.push(fullPath);
  }
  return results;
}

function resolveSiteUnitPath(args) {
  if (args.siteunit) return path.resolve(args.siteunit);
  const firmwareRoot = path.resolve(args["firmware-root"] || DEFAULT_FIRMWARE_ROOT);
  const direct = path.join(firmwareRoot, "SiteUnit");
  if (fs.existsSync(direct)) return direct;
  const matches = walkFiles(firmwareRoot, "SiteUnit");
  if (matches.length === 1) return matches[0];
  if (matches.length > 1) return matches.sort((a, b) => a.length - b.length || a.localeCompare(b))[0];
  throw new Error(`SiteUnit not found under firmware root: ${firmwareRoot}`);
}

function hex(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  return `0x${Number(value).toString(16)}`;
}

function readCString(buffer, offset) {
  let end = offset;
  while (end < buffer.length && buffer[end] !== 0) end += 1;
  return buffer.toString("ascii", offset, end);
}

function parseElf(buffer) {
  if (buffer.length < 52 || buffer[0] !== 0x7f || buffer.toString("ascii", 1, 4) !== "ELF") {
    throw new Error("not an ELF file");
  }
  const elfClass = buffer[4] === 1 ? "ELF32" : `class-${buffer[4]}`;
  const endian = buffer[5] === 1 ? "LSB" : `endian-${buffer[5]}`;
  if (elfClass !== "ELF32" || endian !== "LSB") {
    throw new Error(`unsupported ELF encoding: ${elfClass} ${endian}`);
  }
  const header = {
    elfClass,
    endian,
    osAbi: buffer[7],
    type: buffer.readUInt16LE(16),
    machine: buffer.readUInt16LE(18),
    architecture: buffer.readUInt16LE(18) === 40 ? "ARM" : `e_machine_${buffer.readUInt16LE(18)}`,
    entryPoint: buffer.readUInt32LE(24),
    programHeaderOffset: buffer.readUInt32LE(28),
    sectionHeaderOffset: buffer.readUInt32LE(32),
    flags: buffer.readUInt32LE(36),
    headerSize: buffer.readUInt16LE(40),
    programHeaderEntrySize: buffer.readUInt16LE(42),
    programHeaderCount: buffer.readUInt16LE(44),
    sectionHeaderEntrySize: buffer.readUInt16LE(46),
    sectionHeaderCount: buffer.readUInt16LE(48),
    sectionNameStringIndex: buffer.readUInt16LE(50),
  };

  const programHeaders = [];
  for (let i = 0; i < header.programHeaderCount; i += 1) {
    const off = header.programHeaderOffset + i * header.programHeaderEntrySize;
    programHeaders.push({
      index: i,
      type: buffer.readUInt32LE(off),
      offset: buffer.readUInt32LE(off + 4),
      virtualAddress: buffer.readUInt32LE(off + 8),
      physicalAddress: buffer.readUInt32LE(off + 12),
      fileSize: buffer.readUInt32LE(off + 16),
      memorySize: buffer.readUInt32LE(off + 20),
      flags: buffer.readUInt32LE(off + 24),
      align: buffer.readUInt32LE(off + 28),
    });
  }

  const rawSections = [];
  for (let i = 0; i < header.sectionHeaderCount; i += 1) {
    const off = header.sectionHeaderOffset + i * header.sectionHeaderEntrySize;
    rawSections.push({
      index: i,
      nameOffset: buffer.readUInt32LE(off),
      type: buffer.readUInt32LE(off + 4),
      flags: buffer.readUInt32LE(off + 8),
      virtualAddress: buffer.readUInt32LE(off + 12),
      offset: buffer.readUInt32LE(off + 16),
      size: buffer.readUInt32LE(off + 20),
      link: buffer.readUInt32LE(off + 24),
      info: buffer.readUInt32LE(off + 28),
      align: buffer.readUInt32LE(off + 32),
      entrySize: buffer.readUInt32LE(off + 36),
    });
  }

  const shstr = rawSections[header.sectionNameStringIndex];
  const sectionHeaders = rawSections.map((section) => ({
    ...section,
    name: readCString(buffer, shstr.offset + section.nameOffset),
  }));

  return { header, programHeaders, sectionHeaders };
}

function fileOffsetToVirtualAddress(sections, fileOffset) {
  const section = sections.find((item) => item.size > 0 && fileOffset >= item.offset && fileOffset < item.offset + item.size);
  if (!section || !section.virtualAddress) return { virtualAddress: null, section: section ? section.name : null };
  return {
    virtualAddress: section.virtualAddress + (fileOffset - section.offset),
    section: section.name,
    delta: section.virtualAddress - section.offset,
  };
}

function sectionSummary(section) {
  return {
    name: section.name,
    fileOffset: section.offset,
    fileOffsetHex: hex(section.offset),
    virtualAddress: section.virtualAddress,
    virtualAddressHex: hex(section.virtualAddress),
    size: section.size,
    sizeHex: hex(section.size),
    vmaMinusFileOffset: section.virtualAddress - section.offset,
    vmaMinusFileOffsetHex: hex(section.virtualAddress - section.offset),
    flags: section.flags,
    flagsHex: hex(section.flags),
  };
}

function markdownTable(rows, columns) {
  const header = `| ${columns.map((column) => column.title).join(" | ")} |`;
  const divider = `| ${columns.map(() => "---").join(" | ")} |`;
  const body = rows.map((row) => `| ${columns.map((column) => String(column.value(row)).replace(/\|/g, "\\|")).join(" | ")} |`);
  return [header, divider, ...body].join("\n");
}

function writeReports(outDir, report) {
  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `siteunit-elf-map-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");

  const md = [
    "# SiteUnit ELF Map",
    "",
    `Generated: ${report.generatedAt}`,
    `Path: ${report.fileInfo.path}`,
    `Size: ${report.fileInfo.size}`,
    `SHA256: ${report.fileInfo.sha256}`,
    "",
    "## ELF Header",
    "",
    `Architecture: ${report.header.architecture}`,
    `Endian: ${report.header.endian}`,
    `Entry point: ${report.header.entryPointHex}`,
    `Program headers: ${report.header.programHeaderCount}`,
    `Section headers: ${report.header.sectionHeaderCount}`,
    "",
    "## Program Headers",
    "",
    markdownTable(report.programHeaders, [
      { title: "Index", value: (row) => row.index },
      { title: "Type", value: (row) => row.typeHex },
      { title: "Offset", value: (row) => row.offsetHex },
      { title: "VA", value: (row) => row.virtualAddressHex },
      { title: "File Size", value: (row) => row.fileSizeHex },
      { title: "Mem Size", value: (row) => row.memorySizeHex },
      { title: "Flags", value: (row) => row.flagsHex },
    ]),
    "",
    "## Section Headers",
    "",
    markdownTable(report.sectionHeaders, [
      { title: "Index", value: (row) => row.index },
      { title: "Name", value: (row) => row.name },
      { title: "Offset", value: (row) => row.fileOffsetHex },
      { title: "VA", value: (row) => row.virtualAddressHex },
      { title: "Size", value: (row) => row.sizeHex },
      { title: "Delta", value: (row) => row.vmaMinusFileOffsetHex },
      { title: "Flags", value: (row) => row.flagsHex },
    ]),
    "",
    "## Key Sections",
    "",
    markdownTable(report.keySections, [
      { title: "Name", value: (row) => row.name },
      { title: "Offset", value: (row) => row.fileOffsetHex },
      { title: "VA", value: (row) => row.virtualAddressHex },
      { title: "Size", value: (row) => row.sizeHex },
      { title: "Delta", value: (row) => row.vmaMinusFileOffsetHex },
    ]),
    "",
    "## Offset Verification",
    "",
    markdownTable(report.verification, [
      { title: "File Offset", value: (row) => row.fileOffsetHex },
      { title: "Expected VA", value: (row) => row.expectedVirtualAddressHex },
      { title: "Actual VA", value: (row) => row.virtualAddressHex },
      { title: "Section", value: (row) => row.section },
      { title: "OK", value: (row) => row.ok },
    ]),
    "",
  ].join("\n");
  const mdPath = path.join(outDir, `siteunit-elf-map-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { jsonPath, mdPath };
}

function main() {
  const args = parseArgs(process.argv);
  const siteUnitPath = resolveSiteUnitPath(args);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const buffer = fs.readFileSync(siteUnitPath);
  const elf = parseElf(buffer);
  const sectionHeaders = elf.sectionHeaders.map((section) => ({ index: section.index, ...sectionSummary(section) }));
  const programHeaders = elf.programHeaders.map((ph) => ({
    ...ph,
    typeHex: hex(ph.type),
    offsetHex: hex(ph.offset),
    virtualAddressHex: hex(ph.virtualAddress),
    physicalAddressHex: hex(ph.physicalAddress),
    fileSizeHex: hex(ph.fileSize),
    memorySizeHex: hex(ph.memorySize),
    flagsHex: hex(ph.flags),
    alignHex: hex(ph.align),
  }));
  const keySections = [".text", ".rodata", ".data"]
    .map((name) => elf.sectionHeaders.find((section) => section.name === name))
    .filter(Boolean)
    .map(sectionSummary);
  const expected = new Map([
    [0x6e878, 0x76878],
    [0x6d77c, 0x7577c],
    [0x6f634, 0x77634],
  ]);
  const verification = VERIFY_OFFSETS.map((fileOffset) => {
    const mapped = fileOffsetToVirtualAddress(elf.sectionHeaders, fileOffset);
    return {
      fileOffset,
      fileOffsetHex: hex(fileOffset),
      expectedVirtualAddress: expected.get(fileOffset),
      expectedVirtualAddressHex: hex(expected.get(fileOffset)),
      virtualAddress: mapped.virtualAddress,
      virtualAddressHex: hex(mapped.virtualAddress),
      section: mapped.section,
      delta: mapped.delta,
      deltaHex: hex(mapped.delta),
      ok: mapped.virtualAddress === expected.get(fileOffset),
    };
  });

  const report = {
    generatedAt: new Date().toISOString(),
    fileInfo: {
      path: siteUnitPath,
      size: buffer.length,
      sha256: crypto.createHash("sha256").update(buffer).digest("hex"),
    },
    header: {
      ...elf.header,
      entryPointHex: hex(elf.header.entryPoint),
      flagsHex: hex(elf.header.flags),
    },
    programHeaders,
    sectionHeaders,
    keySections,
    verification,
  };
  const paths = writeReports(outDir, report);
  console.log(JSON.stringify({ ...paths, verification }, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
