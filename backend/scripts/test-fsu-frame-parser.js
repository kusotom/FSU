#!/usr/bin/env node
"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const { parseFsuFrame } = require("../app/modules/fsu_gateway/parser/fsu-frame-parser");

const FIXTURE_DIR = path.join(__dirname, "..", "fixtures", "fsu");

const EXPECTATIONS = [
  {
    file: "udp_dsc_len24.json",
    expectedClass: "DSC_SHORT_24_TYPE_1F00_D2FF",
    requireUri: false,
  },
  {
    file: "udp_dsc_len209.json",
    expectedClass: "DSC_CONFIG_209_TYPE_1100_46FF",
    requireUri: true,
  },
  {
    file: "udp_dsc_len245.json",
    expectedClass: "DSC_CONFIG_245_TYPE_1100_46FF",
    requireUri: true,
  },
  {
    file: "udp_rds_len30.json",
    expectedClass: "RDS_SHORT_30_TYPE_1180_D2FF",
    requireUri: false,
  },
];

function loadFixture(file) {
  const filePath = path.join(FIXTURE_DIR, file);
  assert.ok(fs.existsSync(filePath), `fixture not found: ${filePath}`);
  const samples = JSON.parse(fs.readFileSync(filePath, "utf8"));
  assert.ok(Array.isArray(samples), `fixture must be an array: ${filePath}`);
  return samples;
}

function main() {
  const summary = [];
  let total = 0;

  for (const expectation of EXPECTATIONS) {
    const samples = loadFixture(expectation.file);
    let uriSamples = 0;
    let ftpDhcpSamples = 0;
    let ftpExplicitIpSamples = 0;
    let dhcpPlaceholderSamples = 0;
    let explicitIpSamples = 0;
    let usernameRootSamples = 0;
    let passwordHelloSamples = 0;

    samples.forEach((sample, index) => {
      const parsed = parseFsuFrame(sample.rawHex, {
        protocol: sample.protocol,
        includePayloadHex: false,
        includeAscii: true,
      });

      assert.strictEqual(parsed.ok, true, `${expectation.file} sample ${index + 1}: parse ok`);
      assert.strictEqual(parsed.headerHex, "6d7e", `${expectation.file} sample ${index + 1}: headerHex`);
      assert.strictEqual(
        parsed.frameClass,
        expectation.expectedClass,
        `${expectation.file} sample ${index + 1}: frameClass`,
      );
      assert.strictEqual(
        parsed.payloadLengthMatchesTotalMinus24,
        true,
        `${expectation.file} sample ${index + 1}: payload length candidate`,
      );

      if (expectation.requireUri && parsed.uris.some((uri) => uri.startsWith("udp://") || uri.startsWith("ftp://"))) {
        uriSamples += 1;
      }

      if (expectation.expectedClass === "DSC_CONFIG_209_TYPE_1100_46FF") {
        assert.ok(parsed.dscConfig, `${expectation.file} sample ${index + 1}: dscConfig present`);
        assert.ok(
          parsed.dscConfig.udpUris.some((uri) => uri.startsWith("udp://")),
          `${expectation.file} sample ${index + 1}: udp URI extracted`,
        );
        if (parsed.dscConfig.ftpUris.includes("ftp://root:hello@[dhcp]")) {
          ftpDhcpSamples += 1;
        }
        if (parsed.dscConfig.usesDhcpPlaceholder) {
          dhcpPlaceholderSamples += 1;
        }
        if (parsed.dscConfig.usernameCandidates.includes("root")) {
          usernameRootSamples += 1;
        }
        if (parsed.dscConfig.passwordCandidates.includes("hello")) {
          passwordHelloSamples += 1;
        }
      }

      if (expectation.expectedClass === "DSC_CONFIG_245_TYPE_1100_46FF") {
        assert.ok(parsed.dscConfig, `${expectation.file} sample ${index + 1}: dscConfig present`);
        assert.ok(
          parsed.dscConfig.udpUris.some((uri) => uri.startsWith("udp://")),
          `${expectation.file} sample ${index + 1}: udp URI extracted`,
        );
        if (parsed.dscConfig.ftpUris.includes("ftp://root:hello@192.168.100.100")) {
          ftpExplicitIpSamples += 1;
        }
        if (parsed.dscConfig.usesExplicitIp) {
          explicitIpSamples += 1;
        }
        if (parsed.dscConfig.usernameCandidates.includes("root")) {
          usernameRootSamples += 1;
        }
        if (parsed.dscConfig.passwordCandidates.includes("hello")) {
          passwordHelloSamples += 1;
        }
      }
    });

    if (expectation.requireUri) {
      assert.strictEqual(uriSamples, samples.length, `${expectation.file}: every sample extracts udp:// or ftp://`);
    }
    if (expectation.expectedClass === "DSC_CONFIG_209_TYPE_1100_46FF") {
      assert.strictEqual(ftpDhcpSamples, samples.length, `${expectation.file}: ftp://root:hello@[dhcp] extracted`);
      assert.strictEqual(dhcpPlaceholderSamples, samples.length, `${expectation.file}: usesDhcpPlaceholder`);
      assert.strictEqual(usernameRootSamples, samples.length, `${expectation.file}: usernameCandidate root`);
      assert.strictEqual(passwordHelloSamples, samples.length, `${expectation.file}: passwordCandidate hello`);
    }
    if (expectation.expectedClass === "DSC_CONFIG_245_TYPE_1100_46FF") {
      assert.strictEqual(
        ftpExplicitIpSamples,
        samples.length,
        `${expectation.file}: ftp://root:hello@192.168.100.100 extracted`,
      );
      assert.strictEqual(explicitIpSamples, samples.length, `${expectation.file}: usesExplicitIp`);
      assert.strictEqual(usernameRootSamples, samples.length, `${expectation.file}: usernameCandidate root`);
      assert.strictEqual(passwordHelloSamples, samples.length, `${expectation.file}: passwordCandidate hello`);
    }

    total += samples.length;
    summary.push(`${expectation.file}: ${samples.length} passed as ${expectation.expectedClass}`);
  }

  console.log(`FSU frame parser fixture assertions passed: ${total} samples`);
  for (const line of summary) {
    console.log(`- ${line}`);
  }
}

main();
