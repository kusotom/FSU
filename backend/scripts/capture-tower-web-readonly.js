#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");

const ROOT = path.resolve(__dirname, "..", "..");
const OUTPUT_DIR = path.join(ROOT, "backend", "fixtures", "tower_web", "live-capture");
const ENTRY_URL =
  process.argv[2] ||
  "http://omms.chinatowercom.cn:9000/From4A.jsp?loginName=ztfzj&moduleurl=/layout/index.xhtml";
const ALLOWED_HOST = "omms.chinatowercom.cn";
const ALLOWED_PORT = "9000";
const MAX_BODY_BYTES = 4 * 1024 * 1024;
const MAX_GETS = 80;

const KEYWORDS = [
  "FSU", "SC", "B接口", "动环", "监控单元", "站址", "站点", "设备", "信号", "点位", "遥测", "遥信",
  "遥控", "遥调", "告警", "事件", "实时数据", "历史数据", "心跳", "注册", "登录", "上报", "监控中心",
  "上级平台", "通信配置", "协议配置", "DeviceId", "SignalId", "FsuId", "SiteId", "ChannelNo", "DSC",
  "DscIp", "DscPort", "RDS", "RDSIp", "RDSPort", "RDSHeartBeat", "HeartBeat", "RealData", "Register",
  "Login", "ACK", "7000", "9000", "6000", "6001", "6002", "6003",
];

let redactionCount = 0;

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function rel(file) {
  return path.relative(ROOT, file).replace(/\\/g, "/");
}

function redact(text) {
  if (text === null || text === undefined) return text;
  const before = String(text);
  let out = before;
  out = out.replace(/(loginName=)[^&#\s"']+/gi, "$1[REDACTED]");
  out = out.replace(/(Cookie|Set-Cookie|Authorization|JSESSIONID|session(?:id)?|token|access_token|refresh_token|password|passwd|pwd|mobile|phone|账号|手机号)(["'\s:=]+)([^&\s"',;<>}]+)/gi, (_m, key, sep) => `${key}${sep}[REDACTED]`);
  out = out.replace(/([?&](?:token|session|jsessionid|authorization|loginName|password|mobile|phone)=)[^&#\s]+/gi, "$1[REDACTED]");
  if (out !== before) redactionCount += 1;
  return out;
}

function isAllowedUrl(rawUrl) {
  const url = new URL(rawUrl);
  return url.hostname === ALLOWED_HOST && String(url.port || "80") === ALLOWED_PORT;
}

function getUrl(rawUrl, redirectDepth = 0) {
  return new Promise((resolve) => {
    let url;
    try {
      url = new URL(rawUrl);
    } catch (error) {
      resolve({ ok: false, url: rawUrl, error: error.message });
      return;
    }
    if (!isAllowedUrl(url.href)) {
      resolve({ ok: false, url: redact(url.href), skipped: true, reason: "not same allowed host/port" });
      return;
    }
    const client = url.protocol === "https:" ? https : http;
    const req = client.request(
      {
        method: "GET",
        hostname: url.hostname,
        port: url.port,
        path: `${url.pathname}${url.search}`,
        timeout: 15000,
        headers: {
          "User-Agent": "FSU-Readonly-Research/1.0",
          Accept: "text/html,application/xhtml+xml,application/xml,text/css,application/javascript,text/javascript,application/json,*/*;q=0.8",
        },
      },
      (res) => {
        const status = res.statusCode || 0;
        const location = res.headers.location;
        if ([301, 302, 303, 307, 308].includes(status) && location && redirectDepth < 4) {
          const nextUrl = new URL(location, url).href;
          if (!isAllowedUrl(nextUrl)) {
            resolve({ ok: false, url: redact(url.href), status, redirectTo: redact(nextUrl), skipped: true, reason: "redirect target outside allowed host/port" });
            return;
          }
          getUrl(nextUrl, redirectDepth + 1).then(resolve);
          return;
        }

        const chunks = [];
        let total = 0;
        res.on("data", (chunk) => {
          total += chunk.length;
          if (total <= MAX_BODY_BYTES) chunks.push(chunk);
        });
        res.on("end", () => {
          const buf = Buffer.concat(chunks);
          const contentType = String(res.headers["content-type"] || "");
          resolve({
            ok: true,
            url: redact(url.href),
            status,
            contentType,
            body: redact(buf.toString("utf8")),
            truncated: total > MAX_BODY_BYTES,
          });
        });
      },
    );
    req.on("timeout", () => {
      req.destroy(new Error("timeout"));
    });
    req.on("error", (error) => {
      resolve({ ok: false, url: redact(url.href), error: error.message });
    });
    req.end();
  });
}

function extractUrls(html, baseUrl) {
  const urls = [];
  const patterns = [
    /<script\b[^>]*\bsrc=["']([^"']+)["'][^>]*>/gi,
    /<link\b[^>]*\bhref=["']([^"']+)["'][^>]*>/gi,
    /<(?:iframe|frame)\b[^>]*\bsrc=["']([^"']+)["'][^>]*>/gi,
    /<img\b[^>]*\bsrc=["']([^"']+)["'][^>]*>/gi,
  ];
  for (const regex of patterns) {
    for (const match of html.matchAll(regex)) {
      try {
        const url = new URL(match[1], baseUrl);
        if (isAllowedUrl(url.href)) urls.push(url.href);
      } catch (_error) {
        // Ignore malformed resource URLs.
      }
    }
  }
  return [...new Set(urls)];
}

function extractFrames(html, baseUrl) {
  const rows = [];
  for (const match of html.matchAll(/<(iframe|frame)\b([^>]*)>/gi)) {
    const attrs = {};
    for (const attr of match[2].matchAll(/([\w:-]+)\s*=\s*["']([^"']*)["']/g)) attrs[attr[1]] = redact(attr[2]);
    const src = attrs.src ? redact(new URL(attrs.src, baseUrl).href) : "";
    rows.push({ tag: match[1].toLowerCase(), src, id: attrs.id || "", name: attrs.name || "", title: attrs.title || "" });
  }
  return rows;
}

function extractFields(html, sourceFile, pageTitle = "") {
  const labels = [...html.matchAll(/<label[^>]*>([\s\S]*?)<\/label>/gi)].map((m) => m[1].replace(/<[^>]+>/g, "").trim()).filter(Boolean);
  const headers = [...html.matchAll(/<th[^>]*>([\s\S]*?)<\/th>/gi)].map((m) => m[1].replace(/<[^>]+>/g, "").trim()).filter(Boolean);
  const buttons = [...html.matchAll(/<button[^>]*>([\s\S]*?)<\/button>/gi)].map((m) => m[1].replace(/<[^>]+>/g, "").trim()).filter(Boolean);
  const inputs = [...html.matchAll(/<(input|select|textarea)\b([^>]*)>/gi)].map((m) => {
    const attrs = {};
    for (const attr of m[2].matchAll(/([\w:-]+)\s*=\s*["']([^"']*)["']/g)) attrs[attr[1]] = redact(attr[2]);
    return {
      sourceFile,
      pageTitle,
      tag: m[1].toLowerCase(),
      name: attrs.name || "",
      id: attrs.id || "",
      placeholder: attrs.placeholder || "",
      value: attrs.value || "",
      readonly: Object.prototype.hasOwnProperty.call(attrs, "readonly") || Object.prototype.hasOwnProperty.call(attrs, "disabled"),
    };
  });
  return { labels, tableHeaders: headers, buttonTextsOnly: buttons, inputs };
}

function extractKeywords(text, sourceFile) {
  const rows = [];
  const lines = text.split(/\r?\n/);
  lines.forEach((line, idx) => {
    for (const keyword of KEYWORDS) {
      if (line.toLowerCase().includes(keyword.toLowerCase())) {
        rows.push({
          keyword,
          sourceFile,
          lineNumber: idx + 1,
          nearbyText: redact(lines.slice(Math.max(0, idx - 2), Math.min(lines.length, idx + 3)).join(" ").replace(/\s+/g, " ").trim()).slice(0, 500),
        });
      }
    }
  });
  return rows;
}

function safeFileName(index, rawUrl, contentType) {
  const url = new URL(rawUrl);
  const extFromPath = path.extname(url.pathname).replace(/[^.\w-]/g, "");
  let ext = extFromPath || ".txt";
  if (!extFromPath) {
    if (/html/i.test(contentType)) ext = ".html";
    else if (/javascript/i.test(contentType)) ext = ".js";
    else if (/css/i.test(contentType)) ext = ".css";
    else if (/json/i.test(contentType)) ext = ".json";
  }
  return `resource-${String(index).padStart(3, "0")}${ext}`;
}

async function main() {
  ensureDir(OUTPUT_DIR);
  const homepage = await getUrl(ENTRY_URL);
  const capture = {
    capturedAt: new Date().toISOString(),
    entryUrl: redact(ENTRY_URL),
    homepage: {
      ok: homepage.ok,
      status: homepage.status || null,
      url: homepage.url,
      contentType: homepage.contentType || "",
      error: homepage.error || null,
    },
    getOnly: true,
    writeMethodsUsed: [],
    resources: [],
    possibleLoginRequired: false,
  };

  const homepageHtml = homepage.ok ? homepage.body || "" : "";
  fs.writeFileSync(path.join(OUTPUT_DIR, "homepage.html"), homepageHtml, "utf8");

  const title = (homepageHtml.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || [null, ""])[1].replace(/<[^>]+>/g, "").trim();
  capture.homepage.title = redact(title);
  capture.possibleLoginRequired = /登录|login|password|验证码|认证|4A|统一认证/i.test(homepageHtml);

  const frames = extractFrames(homepageHtml, ENTRY_URL);
  const fields = extractFields(homepageHtml, "homepage.html", title);
  let keywords = extractKeywords(homepageHtml, "homepage.html");
  const resourceUrls = extractUrls(homepageHtml, ENTRY_URL).slice(0, MAX_GETS);

  let index = 1;
  for (const url of resourceUrls) {
    const result = await getUrl(url);
    const item = {
      url: redact(url),
      ok: result.ok,
      status: result.status || null,
      contentType: result.contentType || "",
      savedAs: "",
      error: result.error || null,
      skipped: result.skipped || false,
      reason: result.reason || "",
    };
    if (result.ok && typeof result.body === "string") {
      const fileName = safeFileName(index, url, result.contentType || "");
      item.savedAs = fileName;
      fs.writeFileSync(path.join(OUTPUT_DIR, fileName), result.body, "utf8");
      keywords = keywords.concat(extractKeywords(result.body, fileName));
      if (/html/i.test(result.contentType || "") || /\.x?html?$/i.test(fileName)) {
        const subFields = extractFields(result.body, fileName, "");
        fields.labels.push(...subFields.labels);
        fields.tableHeaders.push(...subFields.tableHeaders);
        fields.buttonTextsOnly.push(...subFields.buttonTextsOnly);
        fields.inputs.push(...subFields.inputs);
      }
    }
    capture.resources.push(item);
    index += 1;
  }

  const readonlyGetResponses = capture.resources
    .filter((item) => item.ok && /json|xml|text|html|javascript|css/i.test(item.contentType || ""))
    .map((item) => ({ method: "GET", url: item.url, status: item.status, contentType: item.contentType, savedAs: item.savedAs }));

  const menu = fields.buttonTextsOnly
    .concat(fields.labels)
    .filter((text) => /FSU|动环|站址|站点|设备|信号|点位|遥测|遥信|告警|实时|历史|监控/i.test(text))
    .map((text) => ({ menuText: redact(text), source: "extracted text only" }));

  fs.writeFileSync(path.join(OUTPUT_DIR, "menu.json"), JSON.stringify(menu, null, 2), "utf8");
  fs.writeFileSync(path.join(OUTPUT_DIR, "frames.json"), JSON.stringify(frames, null, 2), "utf8");
  fs.writeFileSync(path.join(OUTPUT_DIR, "static-resources.json"), JSON.stringify(capture.resources, null, 2), "utf8");
  fs.writeFileSync(path.join(OUTPUT_DIR, "readonly-get-responses.json"), JSON.stringify(readonlyGetResponses, null, 2), "utf8");
  fs.writeFileSync(path.join(OUTPUT_DIR, "extracted-fields.json"), JSON.stringify(fields, null, 2), "utf8");
  fs.writeFileSync(path.join(OUTPUT_DIR, "extracted-keywords.json"), JSON.stringify(keywords, null, 2), "utf8");
  fs.writeFileSync(
    path.join(OUTPUT_DIR, "redaction-report.json"),
    JSON.stringify(
      {
        redactionCount,
        redactedCategories: ["Cookie", "Authorization", "Token", "Session", "JSESSIONID", "loginName", "password", "mobile", "phone"],
        safety: {
          onlyGetRequests: true,
          noPostPutDeletePatch: true,
          noFormSubmit: true,
          noButtonsClicked: true,
          noInputsModified: true,
        },
      },
      null,
      2,
    ),
    "utf8",
  );
  fs.writeFileSync(path.join(OUTPUT_DIR, "capture-summary.json"), JSON.stringify(capture, null, 2), "utf8");
  console.log(
    JSON.stringify(
      {
        outputDir: rel(OUTPUT_DIR),
        homepageStatus: capture.homepage.status,
        homepageTitle: capture.homepage.title,
        resourcesFetched: capture.resources.filter((item) => item.ok).length,
        possibleLoginRequired: capture.possibleLoginRequired,
        keywordHits: keywords.length,
        redactionCount,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
