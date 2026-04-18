import assert from "node:assert/strict";
import { File } from "node:buffer";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

if (!globalThis.File) {
  globalThis.File = File;
}

const workerSourcePath = new URL("./worker/worker.js", import.meta.url);
const workerSource = readFileSync(workerSourcePath, "utf8");
const workerModuleUrl = `data:text/javascript;charset=utf-8,${encodeURIComponent(workerSource)}`;
const { default: worker } = await import(workerModuleUrl);

function okJsonResponse() {
  return new Response(JSON.stringify({ ok: true, result: {} }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

async function testMixedMediaUsesSeparateTelegramRequests() {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return okJsonResponse();
  };

  const form = new FormData();
  form.append("message", "bug report");
  form.append("file1", new File(["img"], "shot.png", { type: "image/png" }));
  form.append("file2", new File(["doc"], "log.txt", { type: "text/plain" }));

  const response = await worker.fetch(new Request("https://example.com", { method: "POST", body: form }), {
    BOT_TOKEN: "token",
    CHAT_ID: "chat",
  });

  assert.equal(response.status, 200, "混合附件请求应成功");
  assert.equal(calls.length, 3, "混合附件应拆成文本 + 图片 + 文档三次 Telegram 请求");
  assert.match(calls[0].url, /sendMessage$/, "第一步应先发文本消息");
  assert.match(calls[1].url, /sendPhoto|sendMediaGroup$/, "第二步应发送图片");
  assert.match(calls[2].url, /sendDocument|sendMediaGroup$/, "第三步应发送文档");
}

async function testSixFilesRemainAllowed() {
  globalThis.fetch = async () => okJsonResponse();

  const form = new FormData();
  form.append("message", "bug report");
  for (let index = 1; index <= 6; index += 1) {
    form.append(`file${index}`, new File([`doc-${index}`], `file-${index}.txt`, { type: "text/plain" }));
  }

  const response = await worker.fetch(new Request("https://example.com", { method: "POST", body: form }), {
    BOT_TOKEN: "token",
    CHAT_ID: "chat",
  });

  assert.equal(response.status, 200, "6 个附件应在报错反馈场景下允许通过");
}

await testMixedMediaUsesSeparateTelegramRequests();
await testSixFilesRemainAllowed();

console.log("contact worker tests passed");
