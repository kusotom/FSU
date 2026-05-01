#!/usr/bin/env node
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

function loadJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function markdownTable(rows, columns) {
  const header = `| ${columns.map((column) => column.title).join(" | ")} |`;
  const divider = `| ${columns.map(() => "---").join(" | ")} |`;
  const body = rows.map((row) => `| ${columns.map((column) => String(column.value(row) ?? "").replace(/\|/g, "\\|")).join(" | ")} |`);
  return [header, divider, ...body].join("\n");
}

function insn(region, address) {
  const found = region.instructions.find((item) => item.address === address);
  if (!found) return null;
  return {
    address: found.address,
    addressHex: found.addressHex,
    fileOffsetHex: found.fileOffsetHex,
    bytes: found.bytes,
    mnemonic: found.mnemonic,
    opStr: found.opStr,
    text: `${found.mnemonic} ${found.opStr}`,
    literal: found.pcrelLiteral
      ? {
          valueHex: found.pcrelLiteral.valueHex,
          constant: found.pcrelLiteral.constant,
          string: found.pcrelLiteral.string ? found.pcrelLiteral.string.text : null,
        }
      : null,
    branchTargetHex: found.branchTargetHex,
  };
}

function insnRange(region, start, end) {
  return region.instructions
    .filter((item) => item.address >= start && item.address <= end)
    .map((item) => insn(region, item.address));
}

function buildParseReport(disasmReport, outDir) {
  const parseRegion = disasmReport.regions.find((region) => region.name === "ParseData");
  const checksumRegion = disasmReport.regions.find((region) => region.name === "Checksum candidate 0x7f98c");
  if (!parseRegion) throw new Error("ParseData region not found in disasm report");

  const branches = {
    soiFail: {
      description: "buffer[0..1] halfword must equal 0x7e6d, which corresponds to bytes 6d 7e.",
      instructions: insnRange(parseRegion, 0x7610c, 0x7613c),
      comparison: {
        registerA: "r2 = uint16_le(buffer + 0x00)",
        registerB: "r3 = literal 0x00007e6d",
        branch: "beq 0x76140 continues; otherwise logs fail SOI and returns 0",
        bufferOffset: "0x00",
      },
    },
    checksumFail: {
      description: "Saves uint16 checksum from buffer+0x16, zeroes that field, computes checksum over the frame, compares computed vs saved.",
      instructions: insnRange(parseRegion, 0x76140, 0x761e4),
      comparison: {
        registerA: "r2 = computed checksum returned from 0x7f98c, stored at [fp-0x38]",
        registerB: "r3 = saved checksum from uint16_le(buffer + 0x16), stored at [fp-0x36]",
        branch: "beq 0x761e8 continues; otherwise logs fail checksum and returns 0",
        bufferOffset: "0x16",
      },
    },
    lengthFail: {
      description: "Length field at buffer+0x14 must equal totalLen - 0x18.",
      instructions: insnRange(parseRegion, 0x761e8, 0x76224),
      comparison: {
        registerA: "r2 = uint16_le(buffer + 0x14)",
        registerB: "r3 = totalLen - 0x18",
        branch: "beq 0x76228 continues; otherwise logs fail length and returns 0",
        bufferOffset: "0x14",
      },
    },
    dsBusy: {
      description: "DS busy flag is bit 0x40 in buffer[0x05].",
      instructions: insnRange(parseRegion, 0x76324, 0x76358),
      comparison: {
        registerA: "r3 = buffer[0x05] & 0x40",
        registerB: "0",
        branch: "beq 0x76358 skips busy path; nonzero sets ctx+0x128 to 1 and logs DS busy",
        bufferOffset: "0x05 bit 0x40",
      },
    },
    successDispatch: {
      description: "After validation, command byte buffer[0x06] drives a switch-like dispatch to handlers.",
      instructions: insnRange(parseRegion, 0x76358, 0x76410),
      comparison: {
        registerA: "r2/r3 = command byte from buffer[0x06]",
        registerB: "case constants 0x0a,0x0c,0x14,0x16,0x32,0x3c,0x3f,0x47,0xd3,0xd6",
        branch: "known cases call handler functions; unknown defaults to status 1",
        bufferOffset: "0x06",
      },
    },
  };

  const checksumFunction = checksumRegion
    ? {
        functionVa: "0x7f98c",
        fileOffset: "0x7798c",
        instructions: insnRange(checksumRegion, 0x7f98c, 0x7fa08),
        pseudocode: [
          "uint16 additiveChecksum16(uint8_t *buffer, uint32_t totalLen) {",
          "  uint16_t acc = 0;",
          "  for (uint32_t i = 2; i < totalLen; i++) {",
          "    acc = (uint16_t)(acc + buffer[i]);",
          "  }",
          "  return acc;",
          "}",
        ].join("\n"),
      }
    : null;

  const pseudocode = [
    "int parseDataCandidate(void *ctx, unknown r1, unknown r2, unknown r3, uint32_t totalLen, uint8_t *buffer, uint16_t *outSeq) {",
    "  // Stack/calling convention inference: r0 is ctx; totalLen, buffer, outSeq are stack-passed.",
    "  if (read_u16_le(buffer + 0x00) != 0x7e6d) return 0;",
    "",
    "  uint16_t savedChecksum = read_u16_le(buffer + 0x16);",
    "  write_u16_le(buffer + 0x16, 0);",
    "  uint16_t computedChecksum = additiveChecksum16(buffer, totalLen);",
    "  if (computedChecksum != savedChecksum) return 0;",
    "",
    "  uint16_t expectedPayloadLen = (uint16_t)(totalLen - 0x18);",
    "  if (read_u16_le(buffer + 0x14) != expectedPayloadLen) return 0;",
    "",
    "  *(uint32_t *)(ctx + 0x54) = *(uint32_t *)(buffer + 0x0c);",
    "  if (buffer[0x05] < 0) {",
    "    // Sign-bit path rewrites type/length/checksum fields and calls a handler; exact purpose unknown.",
    "  }",
    "  if (buffer[0x05] & 0x40) *(uint8_t *)(ctx + 0x128) = 1;",
    "",
    "  switch (buffer[0x06]) {",
    "    case 0x47: status = handler_0x7e804(ctx, buffer + 0x18); break;",
    "    case 0x32: status = fillCmd_or_related(ctx, read_u16_le(buffer + 0x02)); break;",
    "    case 0x0a: status = handler_0x7fa0c(ctx, buffer + 0x18); break;",
    "    case 0x0c: status = handler_0x7d458(ctx, buffer + 0x18); break;",
    "    case 0x14: status = handler_0x807b0(ctx, buffer + 0x18); break;",
    "    case 0x16: status = handler_0x80958(ctx, buffer + 0x18); break;",
    "    case 0x3c: status = handler_0x7e4f4(ctx, buffer); break;",
    "    case 0x3f: status = handler_0x82064(ctx, buffer + 0x18); break;",
    "    case 0xd3: status = handler_0x81370(ctx, buffer + 0x18); break;",
    "    case 0xd6: status = handler_0x7e6f0(ctx, buffer + 0x18); break;",
    "    default: status = 1; break;",
    "  }",
    "",
    "  *outSeq = read_u16_le(buffer + 0x02);",
    "  return status;",
    "}",
  ].join("\n");

  const result = {
    generatedAt: new Date().toISOString(),
    source: "backend/logs/fsu_reverse/siteunit-disasm-regions-2026-04-28.json",
    functionBoundary: {
      entryCandidate: { va: "0x760ac", fileOffset: "0x6e0ac" },
      exitCandidate: { va: "0x76a64", fileOffset: "0x6ea64" },
      note: "0x760a4 is a small pre-entry sequence used by at least one caller; 0x760ac is the prologue.",
    },
    parameterInference: {
      r0: "ctx / CTransManager-like object pointer",
      r1: "unknown; saved as part of varargs/state block, no confirmed direct semantic in this report",
      r2: "unknown; saved as part of varargs/state block",
      r3: "unknown; saved as part of varargs/state block",
      stack_0x14: "totalLen, used by checksum and length validation",
      stack_0x18: "buffer pointer",
      stack_0x1c: "outSeq pointer, receives uint16_le(buffer+0x02)",
    },
    branches,
    checksumFunction,
    pseudocode,
  };

  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `parse-data-pseudocode-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");

  const branchRows = Object.entries(branches).map(([name, branch]) => ({
    name,
    description: branch.description,
    bufferOffset: branch.comparison.bufferOffset,
    comparison: `${branch.comparison.registerA} vs ${branch.comparison.registerB}`,
    branch: branch.comparison.branch,
  }));
  const md = [
    "# ParseData Pseudocode",
    "",
    `Generated: ${result.generatedAt}`,
    "",
    "## Function Boundary",
    "",
    `Entry candidate: ${result.functionBoundary.entryCandidate.va} / ${result.functionBoundary.entryCandidate.fileOffset}`,
    `Exit candidate: ${result.functionBoundary.exitCandidate.va} / ${result.functionBoundary.exitCandidate.fileOffset}`,
    result.functionBoundary.note,
    "",
    "## Parameter Inference",
    "",
    markdownTable(Object.entries(result.parameterInference).map(([name, meaning]) => ({ name, meaning })), [
      { title: "Parameter", value: (row) => row.name },
      { title: "Inferred Meaning", value: (row) => row.meaning },
    ]),
    "",
    "## Key Branches",
    "",
    markdownTable(branchRows, [
      { title: "Branch", value: (row) => row.name },
      { title: "Description", value: (row) => row.description },
      { title: "Buffer Offset", value: (row) => row.bufferOffset },
      { title: "Comparison", value: (row) => row.comparison },
      { title: "Flow", value: (row) => row.branch },
    ]),
    "",
    ...Object.entries(branches).flatMap(([name, branch]) => [
      `### ${name}`,
      "",
      markdownTable(branch.instructions, [
        { title: "VA", value: (row) => row.addressHex },
        { title: "File Off", value: (row) => row.fileOffsetHex },
        { title: "Bytes", value: (row) => row.bytes },
        { title: "Instruction", value: (row) => row.text },
        { title: "Literal", value: (row) => row.literal ? row.literal.string || row.literal.constant || row.literal.valueHex : "" },
      ]),
      "",
    ]),
    "## Checksum Function",
    "",
    checksumFunction ? `Function: ${checksumFunction.functionVa}\n\n\`\`\`c\n${checksumFunction.pseudocode}\n\`\`\`` : "Not available.",
    "",
    "## Pseudocode",
    "",
    "```c",
    pseudocode,
    "```",
    "",
  ].join("\n");
  const mdPath = path.join(outDir, `parse-data-pseudocode-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { result, paths: { jsonPath, mdPath } };
}

function buildLoginReport(disasmReport, outDir) {
  const region = disasmReport.regions.find((item) => item.name === "Login/Register");
  if (!region) throw new Error("Login/Register region not found");

  const preRegister = insnRange(region, 0x74e88, 0x74f18);
  const parseCall = insnRange(region, 0x75580, 0x755c0);
  const timeoutRegion = disasmReport.regions.find((item) => item.name === "Login timeout");
  const timeout = timeoutRegion ? insnRange(timeoutRegion, 0x77388, 0x77410) : [];

  const ackFieldChecklist = {
    soi: "6d7e",
    seqStrategyCandidates: ["mirror request seqLE", "request seqLE + 1", "independent platform seq"],
    typeCandidates: [],
    lengthField: "offset 20..21 LE, totalLen - 24",
    checksumField: "offset 22..23 LE if checksum verification passes; algorithm candidate is additive uint16 over bytes [2,totalLen) with checksum field zeroed",
    bodyCandidates: [],
    successCodeCandidates: [],
    unknowns: [
      "response command byte at offset 0x06 needed for login/register success",
      "typeA for DSC login/register response",
      "body layout for LoginToDSC response",
      "semantic name and provenance of ctx+0x129",
      "Success/Fail/UnRegister numeric codes from LogToDS return path",
    ],
  };

  const result = {
    generatedAt: new Date().toISOString(),
    source: "backend/logs/fsu_reverse/siteunit-disasm-regions-2026-04-28.json",
    registerOkCondition: {
      nearestInstructions: preRegister,
      interpretation:
        "After calling 0x76ac4 and logging LoginToDSC Result, code checks result != 0, then checks byte *(ctx + 0x129) == 0. Register OK is printed only when both conditions hold.",
      conditions: [
        "LoginToDSC Result local [fp-0x40] != 0",
        "byte at ctx + 0x129 == 0",
      ],
    },
    parseDataCallPath: {
      nearestInstructions: parseCall,
      interpretation:
        "Receive/read path fills a local response buffer, prepares stack arguments, then calls 0x760a4, the pre-entry sequence leading into ParseData at 0x760ac.",
      call: "0x755bc -> 0x760a4 -> ParseData prologue 0x760ac",
    },
    timeoutPath: {
      nearestInstructions: timeout,
      interpretation:
        "Timeout path compares elapsed/return values and logs Login to Dsc timeout before recreating socket-related state.",
    },
    returnCodeCandidates: {
      success: [],
      fail: [],
      unregister: [],
      note:
        "This pass did not prove numeric Success/Fail/UnRegister codes. Register OK depends on LoginToDSC Result != 0 and ctx+0x129 == 0, but the response field that sets those values still needs caller/handler data-flow.",
    },
    ackFieldChecklist,
  };

  fs.mkdirSync(outDir, { recursive: true });
  const jsonPath = path.join(outDir, `login-register-branch-${DATE_STEM}.json`);
  fs.writeFileSync(jsonPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");

  const md = [
    "# Login/Register Branch Analysis",
    "",
    `Generated: ${result.generatedAt}`,
    "",
    "## Register OK Condition",
    "",
    result.registerOkCondition.interpretation,
    "",
    result.registerOkCondition.conditions.map((item) => `- ${item}`).join("\n"),
    "",
    markdownTable(preRegister, [
      { title: "VA", value: (row) => row.addressHex },
      { title: "File Off", value: (row) => row.fileOffsetHex },
      { title: "Instruction", value: (row) => row.text },
      { title: "Literal", value: (row) => row.literal ? row.literal.string || row.literal.constant || row.literal.valueHex : "" },
    ]),
    "",
    "## ParseData Call Path",
    "",
    result.parseDataCallPath.interpretation,
    "",
    markdownTable(parseCall, [
      { title: "VA", value: (row) => row.addressHex },
      { title: "File Off", value: (row) => row.fileOffsetHex },
      { title: "Instruction", value: (row) => row.text },
      { title: "Literal", value: (row) => row.literal ? row.literal.string || row.literal.constant || row.literal.valueHex : "" },
    ]),
    "",
    "## Timeout Path",
    "",
    result.timeoutPath.interpretation,
    "",
    markdownTable(timeout, [
      { title: "VA", value: (row) => row.addressHex },
      { title: "File Off", value: (row) => row.fileOffsetHex },
      { title: "Instruction", value: (row) => row.text },
      { title: "Literal", value: (row) => row.literal ? row.literal.string || row.literal.constant || row.literal.valueHex : "" },
    ]),
    "",
    "## Return Code Candidates",
    "",
    result.returnCodeCandidates.note,
    "",
    "## ACK Field Checklist",
    "",
    "```json",
    JSON.stringify(ackFieldChecklist, null, 2),
    "```",
    "",
  ].join("\n");
  const mdPath = path.join(outDir, `login-register-branch-${DATE_STEM}.md`);
  fs.writeFileSync(mdPath, md, "utf8");
  return { result, paths: { jsonPath, mdPath } };
}

function main() {
  const args = parseArgs(process.argv);
  const outDir = path.resolve(args["out-dir"] || DEFAULT_OUT_DIR);
  const disasmPath = path.resolve(args.disasm || path.join(outDir, `siteunit-disasm-regions-${DATE_STEM}.json`));
  if (!fs.existsSync(disasmPath)) throw new Error(`disasm report not found: ${disasmPath}`);
  const disasmReport = loadJson(disasmPath);
  const parse = buildParseReport(disasmReport, outDir);
  const login = buildLoginReport(disasmReport, outDir);
  console.log(JSON.stringify({ parseDataPseudocode: parse.paths, loginRegisterBranch: login.paths }, null, 2));
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exit(1);
  }
}
