const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST",
  "Access-Control-Allow-Headers": "Content-Type",
};

const JSON_HEADERS = {
  "Content-Type": "application/json",
  "Access-Control-Allow-Origin": "*",
};

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

async function parseIncomingRequest(request) {
  const contentType = request.headers.get("Content-Type") || "";
  let message = "";
  let userId = "";
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
    if (!userId) {
      userId = extractUserIdFromMessage(message);
    }

    for (const [, value] of form.entries()) {
      if (value instanceof File) {
        files.push(value);
      }
    }

    return { message, files, userId };
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
    if (!userId) {
      userId = extractUserIdFromMessage(message);
    }
    return { message, files, userId };
  }

  const text = await request.text();
  if (text) {
    message = text;
  }
  userId = extractUserIdFromMessage(message);
  return { message, files, userId };
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
  await sendTelegramRequest(apiBase, "sendMessage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text,
      ...options,
    }),
  });
}

async function sendSingleFile(apiBase, chatId, file, caption) {
  const isImage = file.type && file.type.startsWith("image/");
  const form = new FormData();
  form.append("chat_id", chatId);
  form.append(isImage ? "photo" : "document", file, file.name || "upload");
  if (caption) {
    form.append("caption", caption);
  }

  await sendTelegramRequest(apiBase, isImage ? "sendPhoto" : "sendDocument", {
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
  await sendTelegramRequest(apiBase, "sendMediaGroup", {
    method: "POST",
    body: form,
  });
}

async function sendHomogeneousFiles(apiBase, chatId, fileList, caption) {
  if (!fileList.length) {
    return;
  }
  if (fileList.length === 1) {
    await sendSingleFile(apiBase, chatId, fileList[0], caption);
    return;
  }
  await sendMediaGroup(apiBase, chatId, fileList, caption);
}

function buildTaskCallbackData(userId) {
  return `done:${userId}`;
}

function buildTaskCardText(userId) {
  return [
    "待处理工单",
    `工单用户ID：${userId}`,
    "点击下方按钮后，群里会追加一条已处理通知。",
  ].join("\n");
}

async function sendTaskCard(apiBase, chatId, userId) {
  await sendMessage(apiBase, chatId, buildTaskCardText(userId), {
    reply_markup: {
      inline_keyboard: [[{ text: "已处理", callback_data: buildTaskCallbackData(userId) }]],
    },
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

      const { message, files, userId } = await parseIncomingRequest(request);
      const validation = validatePayload(message, files);
      if (!validation.ok) {
        return validation.response;
      }

      const { images, documents } = splitFilesByType(files);

      if (files.length === 0) {
        await sendMessage(apiBase, chatId, message);
        if (userId) {
          await sendTaskCard(apiBase, chatId, userId);
        }
        return jsonResponse({ status: "ok" });
      }

      if (images.length > 0 && documents.length > 0) {
        if (message) {
          await sendMessage(apiBase, chatId, message);
        }
        await sendHomogeneousFiles(apiBase, chatId, images);
        await sendHomogeneousFiles(apiBase, chatId, documents);
        if (userId) {
          await sendTaskCard(apiBase, chatId, userId);
        }
        return jsonResponse({ status: "ok" });
      }

      await sendHomogeneousFiles(apiBase, chatId, files, message || undefined);
      if (userId) {
        await sendTaskCard(apiBase, chatId, userId);
      }
      return jsonResponse({ status: "ok" });
    } catch (error) {
      const message = error instanceof Error ? error.message : "internal_error";
      return jsonResponse({ error: message }, 500);
    }
  },
};
