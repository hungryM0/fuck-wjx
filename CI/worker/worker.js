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

async function parseIncomingRequest(request) {
  const contentType = request.headers.get("Content-Type") || "";
  let message = "";
  const files = [];

  if (contentType.includes("multipart/form-data") || contentType.includes("form-data")) {
    const form = await request.formData();
    const maybeMessage = form.get("message");
    if (typeof maybeMessage === "string") {
      message = maybeMessage;
    }

    for (const [, value] of form.entries()) {
      if (value instanceof File) {
        files.push(value);
      }
    }

    return { message, files };
  }

  if (contentType.includes("application/json")) {
    const body = await request.json();
    if (typeof body?.message === "string") {
      message = body.message;
    }
    return { message, files };
  }

  const text = await request.text();
  if (text) {
    message = text;
  }
  return { message, files };
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
}

async function sendMessage(apiBase, chatId, text) {
  await sendTelegramRequest(apiBase, "sendMessage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text,
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
      const { message, files } = await parseIncomingRequest(request);
      const validation = validatePayload(message, files);
      if (!validation.ok) {
        return validation.response;
      }

      const apiBase = `https://api.telegram.org/bot${botToken}`;
      const { images, documents } = splitFilesByType(files);

      if (files.length === 0) {
        await sendMessage(apiBase, chatId, message);
        return jsonResponse({ status: "ok" });
      }

      if (images.length > 0 && documents.length > 0) {
        if (message) {
          await sendMessage(apiBase, chatId, message);
        }
        await sendHomogeneousFiles(apiBase, chatId, images);
        await sendHomogeneousFiles(apiBase, chatId, documents);
        return jsonResponse({ status: "ok" });
      }

      await sendHomogeneousFiles(apiBase, chatId, files, message || undefined);
      return jsonResponse({ status: "ok" });
    } catch (error) {
      const message = error instanceof Error ? error.message : "internal_error";
      return jsonResponse({ error: message }, 500);
    }
  },
};
