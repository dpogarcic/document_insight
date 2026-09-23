"use strict";

const loginForm = document.querySelector("#login-form");
const uploadForm = document.querySelector("#upload-form");
const identityStatus = document.querySelector("#identity-status");
const uploadStatus = document.querySelector("#upload-status");
const results = document.querySelector("#results");
let accessToken = null;
let canActivate = false;
const selectedTenantId = new URLSearchParams(window.location.search).get("tenant_id");

function setStatus(element, message, error = false) {
  element.textContent = message;
  element.classList.toggle("error", error);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(path, { ...options, headers, cache: "no-store" });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail?.message || "The request could not be completed.");
  }
  return data;
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = loginForm.querySelector('button[type="submit"]');
  button.disabled = true;
  setStatus(identityStatus, "Signing in…");
  try {
    const form = new FormData(loginForm);
    const token = await api("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
    });
    accessToken = token.access_token;
    const identity = await api("/evaluation-corpus/identity");
    if (selectedTenantId && identity.tenant_id !== selectedTenantId) {
      throw new Error("This login belongs to a different tenant than the selected suite.");
    }
    canActivate = identity.can_activate;
    loginForm.querySelector('[name="password"]').value = "";
    document.querySelector("#upload-section").hidden = false;
    setStatus(identityStatus, `Signed in to tenant ${identity.tenant_id} as ${identity.role.replace("_", " ")}. Your user ID: ${identity.user_id}.`);
  } catch (error) {
    accessToken = null;
    canActivate = false;
    document.querySelector("#upload-section").hidden = true;
    setStatus(identityStatus, error.message, true);
  } finally {
    loginForm.querySelector('[name="password"]').value = "";
    button.disabled = false;
  }
});

function textElement(tag, value) {
  const element = document.createElement(tag);
  element.textContent = value;
  return element;
}

function addResult(upload, filename) {
  document.querySelector("#results-section").hidden = false;
  const card = document.createElement("article");
  card.className = "result";
  card.append(textElement("strong", filename));
  card.append(textElement("span", "Document version ID"));
  card.append(textElement("code", upload.document_version_id));
  const copy = textElement("button", "Copy version ID");
  copy.type = "button";
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(upload.document_version_id);
      copy.textContent = "Copied";
    } catch {
      copy.textContent = "Select the version ID above to copy it";
    }
  });
  card.append(copy);
  const state = textElement("p", "Processing: queued");
  state.setAttribute("role", "status");
  card.append(state);
  const activate = textElement("button", "Activate ready version");
  activate.type = "button";
  activate.hidden = true;
  activate.addEventListener("click", async () => {
    activate.disabled = true;
    try {
      await api(`/documents/${upload.document_id}/activate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_version_id: upload.document_version_id }),
      });
      state.textContent = "Activated. Copy the version ID into your evaluation suite.";
      activate.remove();
    } catch (error) {
      state.textContent = error.message;
      activate.disabled = false;
    }
  });
  card.append(activate);
  results.prepend(card);

  async function poll() {
    try {
      const job = await api(`/jobs/${upload.job_id}`);
      state.textContent = `Processing: ${job.status}${job.error_code ? ` (${job.error_code})` : ""}`;
      if (job.status === "ready") {
        if (canActivate) activate.hidden = false;
        else state.textContent = "Ready. Ask a tenant admin to activate this version.";
        return;
      }
      if (job.status === "failed" || job.status === "cancelled") return;
      window.setTimeout(poll, 3000);
    } catch (error) {
      state.textContent = error.message;
    }
  }
  window.setTimeout(poll, 3000);
}

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = uploadForm.querySelector('input[type="file"]').files[0];
  if (!file) return;
  if (file.size > 25 * 1024 * 1024) {
    setStatus(uploadStatus, "The file exceeds 25 MiB.", true);
    return;
  }
  const button = uploadForm.querySelector('button[type="submit"]');
  button.disabled = true;
  setStatus(uploadStatus, "Storing and queueing the document…");
  try {
    const body = new FormData();
    body.append("file", file);
    const upload = await api("/ingest", { method: "POST", body });
    addResult(upload, file.name);
    uploadForm.reset();
    setStatus(uploadStatus, "Upload accepted. Processing status appears below.");
  } catch (error) {
    setStatus(uploadStatus, error.message, true);
  } finally {
    button.disabled = false;
  }
});
