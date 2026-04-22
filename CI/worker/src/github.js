import { DEFAULT_GITHUB_OWNER, DEFAULT_GITHUB_REPO, GITHUB_API_VERSION } from "./constants.js";
import {
  extractIssueMessageContent,
  extractIssueTitleFromMessage,
  extractVersionFromMessage,
  sanitizeIssueTitle,
} from "./message.js";

const DEFAULT_GITHUB_ISSUE_LABELS = ["bot"];

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

function buildGitHubIssueTitle({ issueTitle, message }) {
  const explicitTitle = sanitizeIssueTitle(issueTitle);
  if (explicitTitle) {
    return explicitTitle;
  }

  const extractedTitle = sanitizeIssueTitle(extractIssueTitleFromMessage(message));
  if (extractedTitle) {
    return extractedTitle;
  }

  const messageTitle = sanitizeIssueTitle(extractIssueMessageContent(message));
  if (messageTitle) {
    return messageTitle;
  }

  return "报错反馈";
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

function parseConfiguredIssueLabels(env) {
  const raw = typeof env.GITHUB_ISSUE_LABELS === "string" ? env.GITHUB_ISSUE_LABELS : "";
  const configuredLabels = raw
    .split(",")
    .map((label) => label.trim())
    .filter(Boolean);

  return configuredLabels.length > 0 ? configuredLabels : DEFAULT_GITHUB_ISSUE_LABELS;
}

async function fetchExistingGitHubLabels({ owner, repo, token }) {
  const response = await fetch(`https://api.github.com/repos/${owner}/${repo}/labels?per_page=100`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "SurveyController-Worker",
      "X-GitHub-Api-Version": GITHUB_API_VERSION,
    },
  });

  if (!response.ok) {
    return new Set();
  }

  let result = null;
  try {
    result = await response.json();
  } catch {
    result = null;
  }

  if (!Array.isArray(result)) {
    return new Set();
  }

  return new Set(
    result
      .map((label) => (typeof label?.name === "string" ? label.name.trim() : ""))
      .filter(Boolean),
  );
}

export async function createGitHubIssue(env, payload) {
  const token = env.GITHUB_TOKEN;
  if (!token) {
    return null;
  }

  const owner = env.GITHUB_OWNER || DEFAULT_GITHUB_OWNER;
  const repo = env.GITHUB_REPO || DEFAULT_GITHUB_REPO;
  const existingLabels = await fetchExistingGitHubLabels({ owner, repo, token });
  const labels = parseConfiguredIssueLabels(env).filter((label) => existingLabels.has(label));
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
      ...(labels.length > 0 ? { labels } : {}),
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
