const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST",
  "Access-Control-Allow-Headers": "Content-Type",
};

const JSON_HEADERS = {
  "Content-Type": "application/json",
  "Access-Control-Allow-Origin": "*",
};

const DEFAULT_GITHUB_OWNER = "hungryM0";
const DEFAULT_GITHUB_REPO = "SurveyController";
const GITHUB_API_VERSION = "2022-11-28";

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: JSON_HEADERS,
  });
}

function extractUserIdFromMessage(message) {
  if (typeof message !== "string") {
    return "";
  }
  const match = message.match(/随机IP用户ID：\s*(\d+)/);
  return match ? match[1] : "";
}

function extractMessageLineValue(message, prefix) {
  if (typeof message !== "string" || !prefix) {
    return "";
  }
  const lines = message.split(/\r?\n/);
  for (const line of lines) {
    if (line.startsWith(prefix)) {
      return line.slice(prefix.length).trim();
    }
  }
  return "";
}

function normalizeMessageType(rawType, message) {
  const directType = typeof rawType === "string" ? rawType.trim() : "";
  if (directType) {
    return directType;
  }
  return extractMessageLineValue(message, "类型：");
}

function extractVersionFromMessage(message) {
  return (
    extractMessageLineValue(message, "来源：SurveyController v") ||
    extractMessageLineValue(message, "版本号：SurveyController v")
  );
}

function stripEmailLine(message) {
  if (typeof message !== "string" || !message) {
    return "";
  }
  return message
    .split(/\r?\n/)
    .filter((line) => !line.startsWith("联系邮箱："))
    .join("\n")
    .trim();
}

function sanitizeIssueTitle(title) {
  if (typeof title !== "string") {
    return "";
  }
  return title.replace(/\s+/g, " ").trim().slice(0, 60);
}

function extractIssueTitleFromMessage(message) {
  return extractMessageLineValue(message, "反馈标题：");
}

function extractIssueMessageContent(message) {
  if (typeof message !== "string" || !message.trim()) {
    return "";
  }

  const sanitizedMessage = stripEmailLine(message);
  const match = sanitizedMessage.match(/(?:^|\n)消息：([\s\S]*)$/);
  if (match) {
    return match[1].trim();
  }

  return sanitizedMessage.trim();
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function isGitHubLogFile(file) {
  const fileName = typeof file?.name === "string" ? file.name.toLowerCase() : "";
  return fileName === "fatal_crash.log" || (fileName.startsWith("bug_report_log_") && fileName.endsWith(".txt"));
}

async function buildGitHubLogSections(files) {
  if (!Array.isArray(files) || files.length === 0) {
    return [];
  }

  const sections = [];
  for (const file of files) {
    if (!isGitHubLogFile(file)) {
      continue;
    }

    let text = "";
    try {
      text = await file.text();
    } catch {
      text = "";
    }

    const trimmedText = text.trim();
    if (!trimmedText) {
      continue;
    }

    const truncated = trimmedText.length > 20000;
    const displayText = truncated ? `${trimmedText.slice(0, 20000)}\n\n[日志内容过长，已截断]` : trimmedText;
    sections.push(
      [
        "<details>",
        `<summary>报错日志：${escapeHtml(file.name || "未命名日志")}</summary>`,
        "",
        "<pre><code>",
        escapeHtml(displayText),
        "</code></pre>",
        "</details>",
      ].join("\n"),
    );
  }

  return sections;
}

function buildGitHubIssueTitle({ issueTitle, message, userId, timestamp }) {
  const explicitTitle = sanitizeIssueTitle(issueTitle);
  if (explicitTitle) {
    return explicitTitle;
  }

  const extractedTitle = sanitizeIssueTitle(extractIssueTitleFromMessage(message));
  if (extractedTitle) {
    return extractedTitle;
  }

  return "未命名报错反馈";
}

async function buildGitHubIssueBody({ message, files }) {
  const version = extractVersionFromMessage(message);
  const issueMessage = extractIssueMessageContent(message);
  const logSections = await buildGitHubLogSections(files);

  const lines = [];
  if (version) {
    lines.push(`版本号：SurveyController v${version}`);
  }
  if (issueMessage) {
    lines.push(issueMessage);
  } else {
    lines.push("未提供正文");
  }
  if (logSections.length > 0) {
    lines.push("", ...logSections);
  }

  return lines.join("\n");
}

async function createGitHubIssue(env, payload) {
  const token = env.GITHUB_TOKEN;
  if (!token) {
    return null;
  }

  const owner = env.GITHUB_OWNER || DEFAULT_GITHUB_OWNER;
  const repo = env.GITHUB_REPO || DEFAULT_GITHUB_REPO;
  const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/issues`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "SurveyController-Worker",
      "X-GitHub-Api-Version": GITHUB_API_VERSION,
    },
    body: JSON.stringify({
      title: buildGitHubIssueTitle(payload),
      body: await buildGitHubIssueBody(payload),
    }),
  });

  let result = null;
  try {
    result = await response.json();
  } catch {
    result = null;
  }

  if (!response.ok) {
    const message = result?.message || `github_issue_create_failed_${response.status}`;
    throw new Error(message);
  }

  return {
    number: result?.number || 0,
    url: result?.html_url || "",
  };
}

async function parseIncomingRequest(request) {
  const contentType = request.headers.get("Content-Type") || "";
  let message = "";
  let userId = "";
  let messageType = "";
  let issueTitle = "";
  let timestamp = "";
  const files = [];

  if (contentType.includes("multipart/form-data") || contentType.includes("form-data")) {
    const form = await request.formData();
    const maybeMessage = form.get("message");
    if (typeof maybeMessage === "string") {
      message = maybeMessage;
    }
    const maybeUserId = form.get("userId") ?? form.get("user_id");
    if (typeof maybeUserId === "string") {
      userId = maybeUserId.trim();
    }
    const maybeMessageType = form.get("messageType") ?? form.get("message_type");
    if (typeof maybeMessageType === "string") {
      messageType = maybeMessageType.trim();
    }
    const maybeIssueTitle = form.get("issueTitle") ?? form.get("issue_title");
    if (typeof maybeIssueTitle === "string") {
      issueTitle = maybeIssueTitle.trim();
    }
    const maybeTimestamp = form.get("timestamp");
    if (typeof maybeTimestamp === "string") {
      timestamp = maybeTimestamp.trim();
    }
    if (!userId) {
      userId = extractUserIdFromMessage(message);
    }
    messageType = normalizeMessageType(messageType, message);

    for (const [, value] of form.entries()) {
      if (value instanceof File) {
        files.push(value);
      }
    }

    return { message, files, userId, messageType, issueTitle, timestamp };
  }

  if (contentType.includes("application/json")) {
    const body = await request.json();
    if (typeof body?.message === "string") {
      message = body.message;
    }
    if (typeof body?.userId === "string") {
      userId = body.userId.trim();
    } else if (typeof body?.user_id === "string") {
      userId = body.user_id.trim();
    }
    if (typeof body?.messageType === "string") {
      messageType = body.messageType.trim();
    } else if (typeof body?.message_type === "string") {
      messageType = body.message_type.trim();
    }
    if (typeof body?.issueTitle === "string") {
      issueTitle = body.issueTitle.trim();
    } else if (typeof body?.issue_title === "string") {
      issueTitle = body.issue_title.trim();
    }
    if (typeof body?.timestamp === "string") {
      timestamp = body.timestamp.trim();
    }
    if (!userId) {
      userId = extractUserIdFromMessage(message);
    }
    messageType = normalizeMessageType(messageType, message);
    return { message, files, userId, messageType, issueTitle, timestamp };
  }

  const text = await request.text();
  if (text) {
    message = text;
  }
  userId = extractUserIdFromMessage(message);
  messageType = normalizeMessageType(messageType, message);
  return { message, files, userId, messageType, issueTitle, timestamp };
}

function validatePayload(message, files) {
  const maxFiles = 6;
  const maxFileSize = 10 * 1024 * 1024;

  if (files.length > maxFiles) {
    return { ok: false, response: jsonResponse({ error: `too_many_files_max_${maxFiles}` }, 400) };
  }

  for (const file of files) {
    if (file.size > maxFileSize) {
      return { ok: false, response: jsonResponse({ error: "file_too_large_max_10mb" }, 400) };
    }
  }

  if (!message && files.length === 0) {
    return { ok: false, response: jsonResponse({ error: "no_message_or_files" }, 400) };
  }

  return { ok: true };
}

async function sendTelegramRequest(apiBase, endpoint, init) {
  const response = await fetch(`${apiBase}/${endpoint}`, init);
  let payload = null;

  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok || !payload?.ok) {
    const description = payload?.description || `telegram_request_failed_${response.status}`;
    throw new Error(description);
  }

  return payload.result;
}

async function sendMessage(apiBase, chatId, text, options = {}) {
  return sendTelegramRequest(apiBase, "sendMessage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text,
      ...options,
    }),
  });
}

async function sendSingleFile(apiBase, chatId, file, caption, options = {}) {
  const isImage = file.type && file.type.startsWith("image/");
  const form = new FormData();
  form.append("chat_id", chatId);
  form.append(isImage ? "photo" : "document", file, file.name || "upload");
  if (caption) {
    form.append("caption", caption);
  }
  if (options.reply_markup) {
    form.append("reply_markup", JSON.stringify(options.reply_markup));
  }

  return sendTelegramRequest(apiBase, isImage ? "sendPhoto" : "sendDocument", {
    method: "POST",
    body: form,
  });
}

function splitFilesByType(fileList) {
  const images = [];
  const documents = [];
  for (const file of fileList) {
    const isImage = file.type && file.type.startsWith("image/");
    if (isImage) {
      images.push(file);
    } else {
      documents.push(file);
    }
  }
  return { images, documents };
}

async function sendMediaGroup(apiBase, chatId, fileList, caption) {
  const form = new FormData();
  form.append("chat_id", chatId);

  const media = fileList.map((file, index) => {
    const name = `file${index + 1}`;
    const isImage = file.type && file.type.startsWith("image/");
    form.append(name, file, file.name || name);

    const item = {
      type: isImage ? "photo" : "document",
      media: `attach://${name}`,
    };

    if (index === 0 && caption) {
      item.caption = caption;
    }

    return item;
  });

  form.append("media", JSON.stringify(media));
  return sendTelegramRequest(apiBase, "sendMediaGroup", {
    method: "POST",
    body: form,
  });
}

async function sendHomogeneousFiles(apiBase, chatId, fileList, caption, options = {}) {
  if (!fileList.length) {
    return;
  }
  if (fileList.length === 1) {
    return sendSingleFile(apiBase, chatId, fileList[0], caption, options);
  }
  return sendMediaGroup(apiBase, chatId, fileList, caption);
}

function buildTaskCallbackData(userId) {
  return `done:${userId}`;
}

function buildTaskReplyMarkup(userId) {
  return {
    inline_keyboard: [[{ text: "点击标记为已处理", callback_data: buildTaskCallbackData(userId) }]],
  };
}

async function ensureTelegramWebhook(apiBase, webhookUrl) {
  return sendTelegramRequest(apiBase, "setWebhook", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url: webhookUrl,
      allowed_updates: ["callback_query"],
    }),
  });
}

function escapeMarkdownV2(value) {
  return String(value).replace(/([_*\[\]()~`>#+\-=|{}.!\\])/g, "\\$1");
}

function parseTaskCallbackData(data) {
  if (typeof data !== "string" || !data.startsWith("done:")) {
    return null;
  }

  const userId = data.slice(5).trim();
  if (!userId) {
    return null;
  }

  return { userId };
}

async function answerCallbackQuery(apiBase, callbackQueryId, text) {
  await sendTelegramRequest(apiBase, "answerCallbackQuery", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      callback_query_id: callbackQueryId,
      text,
    }),
  });
}

function getActorDisplayName(from) {
  if (!from || typeof from !== "object") {
    return "未知用户";
  }

  const fullName = [from.first_name, from.last_name].filter(Boolean).join(" ").trim();
  if (fullName) {
    return fullName;
  }
  if (typeof from.username === "string" && from.username.trim()) {
    return from.username.trim();
  }
  return String(from.id || "未知用户");
}

async function handleCallbackQuery(apiBase, callbackQuery) {
  const parsed = parseTaskCallbackData(callbackQuery?.data);
  if (!parsed) {
    return jsonResponse({ error: "unsupported_callback_query" }, 400);
  }

  const callbackQueryId = callbackQuery?.id;
  const chatId = callbackQuery?.message?.chat?.id;
  const actorId = callbackQuery?.from?.id;
  if (!callbackQueryId || chatId === undefined || actorId === undefined) {
    return jsonResponse({ error: "invalid_callback_query_payload" }, 400);
  }

  await answerCallbackQuery(apiBase, callbackQueryId, "已记录处理结果");

  const actorName = escapeMarkdownV2(getActorDisplayName(callbackQuery.from));
  const actorMention = `[${actorName}](tg://user?id=${actorId})`;
  const escapedUserId = escapeMarkdownV2(parsed.userId);
  await sendMessage(
    apiBase,
    chatId,
    `该工单已处理\n处理人：${actorMention}\n工单用户ID：${escapedUserId}`,
    {
      parse_mode: "MarkdownV2",
    },
  );

  return jsonResponse({ status: "ok" });
}

async function parseTelegramUpdate(request) {
  const contentType = request.headers.get("Content-Type") || "";
  if (!contentType.includes("application/json")) {
    return null;
  }

  try {
    const body = await request.clone().json();
    if (body?.callback_query) {
      return body;
    }
  } catch {
    return null;
  }

  return null;
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }

    if (request.method !== "POST") {
      return new Response("Only POST allowed", { status: 405, headers: CORS_HEADERS });
    }

    const botToken = env.BOT_TOKEN;
    const chatId = env.CHAT_ID;
    if (!botToken || !chatId) {
      return jsonResponse({ error: "missing_required_secrets" }, 500);
    }

    try {
      const apiBase = `https://api.telegram.org/bot${botToken}`;
      const telegramUpdate = await parseTelegramUpdate(request);
      if (telegramUpdate?.callback_query) {
        return handleCallbackQuery(apiBase, telegramUpdate.callback_query);
      }

      const { message, files, userId, messageType, issueTitle, timestamp } = await parseIncomingRequest(request);
      const validation = validatePayload(message, files);
      if (!validation.ok) {
        return validation.response;
      }
      const taskReplyMarkup = userId ? buildTaskReplyMarkup(userId) : null;
      const shouldCreateGitHubIssue = messageType === "报错反馈";
      if (userId) {
        await ensureTelegramWebhook(apiBase, request.url);
      }

      const { images, documents } = splitFilesByType(files);
      let githubIssue = null;
      let githubIssueError = "";

      if (files.length === 0) {
        await sendMessage(apiBase, chatId, message, taskReplyMarkup ? { reply_markup: taskReplyMarkup } : {});
      } else if (images.length > 0 && documents.length > 0) {
        if (message) {
          await sendMessage(apiBase, chatId, message, taskReplyMarkup ? { reply_markup: taskReplyMarkup } : {});
        } else if (taskReplyMarkup) {
          await sendMessage(apiBase, chatId, `待处理工单\n工单用户ID：${userId}`, {
            reply_markup: taskReplyMarkup,
          });
        }
        await sendHomogeneousFiles(apiBase, chatId, images);
        await sendHomogeneousFiles(apiBase, chatId, documents);
      } else if (files.length === 1) {
        await sendHomogeneousFiles(
          apiBase,
          chatId,
          files,
          message || undefined,
          taskReplyMarkup ? { reply_markup: taskReplyMarkup } : {},
        );
      } else {
        if (message) {
          await sendMessage(apiBase, chatId, message, taskReplyMarkup ? { reply_markup: taskReplyMarkup } : {});
        } else if (taskReplyMarkup) {
          await sendMessage(apiBase, chatId, `待处理工单\n工单用户ID：${userId}`, {
            reply_markup: taskReplyMarkup,
          });
        }
        await sendHomogeneousFiles(apiBase, chatId, files);
      }

      if (shouldCreateGitHubIssue) {
        try {
          githubIssue = await createGitHubIssue(env, {
            issueTitle,
            message,
            userId,
            timestamp,
            files,
          });
        } catch (error) {
          githubIssueError = error instanceof Error ? error.message : "github_issue_create_failed";
        }
      }

      return jsonResponse({
        status: "ok",
        githubIssue,
        githubIssueError,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "internal_error";
      return jsonResponse({ error: message }, 500);
    }
  },
};
