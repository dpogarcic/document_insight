"use strict";

const form = document.querySelector("[data-suite-form]");

if (form) {
  const caseList = form.querySelector("[data-case-list]");
  const template = document.querySelector("[data-case-template]");
  const preview = form.querySelector("[data-json-preview]");
  const error = form.querySelector("[data-form-error]");
  const casesInput = form.querySelector('[name="test_cases_json"]');
  const corpusInput = form.querySelector('[name="corpus_version_ids_json"]');
  const tenantSelect = form.querySelector('[name="tenant_id"]');
  const uploadLink = form.querySelector("[data-upload-link]");
  const corpusChoice = form.querySelector("[data-corpus-choice]");
  const corpusStatus = form.querySelector("[data-corpus-status]");
  const corpusSelected = form.querySelector("[data-corpus-selected]");
  const selectedCorpus = new Map();
  let corpusRequest = 0;

  function updateUploadLink() {
    const url = new URL(uploadLink.dataset.baseUrl, window.location.href);
    if (tenantSelect.value) {
      url.searchParams.set("tenant_id", tenantSelect.value);
      url.searchParams.set("tenant_name", tenantSelect.selectedOptions[0].textContent.trim());
    }
    uploadLink.href = url.toString();
  }

  function lines(value) {
    return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  }

  function renderSelectedCorpus() {
    corpusSelected.replaceChildren();
    for (const [versionId, label] of selectedCorpus) {
      const item = document.createElement("li");
      const text = document.createElement("span");
      text.textContent = `${label} · ${versionId}`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "button secondary";
      remove.textContent = "Remove";
      remove.setAttribute("aria-label", `Remove ${label}`);
      remove.addEventListener("click", () => {
        selectedCorpus.delete(versionId);
        renderSelectedCorpus();
        refresh();
      });
      item.append(text, remove);
      corpusSelected.append(item);
    }
  }

  function addChosenDocument() {
    const option = corpusChoice.selectedOptions[0];
    if (!option || !option.value) return;
    selectedCorpus.set(option.value, option.dataset.label || option.textContent);
    corpusChoice.value = "";
    renderSelectedCorpus();
    refresh();
  }

  async function loadDocuments(clearSelection) {
    const requestId = ++corpusRequest;
    if (clearSelection) selectedCorpus.clear();
    renderSelectedCorpus();
    refresh();
    corpusChoice.replaceChildren(new Option("Select an activated document", ""));
    corpusChoice.disabled = true;
    if (!tenantSelect.value) {
      corpusStatus.textContent = "Choose a tenant to see its activated documents.";
      return;
    }
    corpusStatus.textContent = "Loading activated documents…";
    try {
      const url = new URL("/evaluations/corpus/versions", window.location.origin);
      url.searchParams.set("tenant_id", tenantSelect.value);
      const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error("Could not load documents for this tenant.");
      const documents = await response.json();
      if (requestId !== corpusRequest) return;
      const available = new Map(documents.map((item) => [item.version_id, item.title]));
      const dropped = [];
      for (const versionId of [...selectedCorpus.keys()]) {
        if (available.has(versionId)) selectedCorpus.set(versionId, available.get(versionId));
        else {
          selectedCorpus.delete(versionId);
          dropped.push(versionId);
        }
      }
      renderSelectedCorpus();
      refresh();
      for (const documentVersion of documents) {
        const option = new Option(
          `${documentVersion.title} · ${documentVersion.version_id.slice(0, 8)}`,
          documentVersion.version_id,
        );
        option.dataset.label = documentVersion.title;
        corpusChoice.add(option);
      }
      corpusChoice.disabled = documents.length === 0;
      corpusStatus.textContent = documents.length
        ? `${documents.length} activated document${documents.length === 1 ? "" : "s"} available.`
        : "No activated documents yet. Upload and activate one, then refresh this list.";
      if (dropped.length) {
        // A saved span that points at a removed version will be rejected on save, so say so now.
        corpusStatus.textContent += ` Removed ${dropped.length} previously selected version${dropped.length === 1 ? "" : "s"} that ${dropped.length === 1 ? "is" : "are"} no longer activated (${dropped.map((id) => id.slice(0, 8)).join(", ")}); update any relevant spans that point to ${dropped.length === 1 ? "it" : "them"}.`;
      }
    } catch (problem) {
      if (requestId === corpusRequest) corpusStatus.textContent = problem.message;
    }
  }

  function field(caseCard, name) {
    return caseCard.querySelector(`[data-field="${name}"]`);
  }

  function objectValue(raw, label, emptyValue) {
    if (!raw.trim()) return emptyValue;
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch {
      throw new Error(`${label} must be a valid JSON object.`);
    }
    if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
      throw new Error(`${label} must be a JSON object.`);
    }
    return parsed;
  }

  function caseValue(caseCard) {
    return {
      question: field(caseCard, "question").value.trim(),
      authorized_identity_id: field(caseCard, "authorized_identity_id").value.trim(),
      answerability: field(caseCard, "answerability").value,
      relevance_complete: field(caseCard, "relevance_complete").checked,
      relevant_passage_ids: lines(field(caseCard, "relevant_passage_ids").value),
      filter_text: field(caseCard, "filter_text").value.trim() || null,
      expected_facts: objectValue(field(caseCard, "expected_facts").value, "Expected facts", null),
      review_rubric: field(caseCard, "review_rubric").value.trim() || null,
      tags: objectValue(field(caseCard, "tags").value, "Tags", {}),
    };
  }

  function refresh() {
    const cards = [...caseList.querySelectorAll("[data-case]")];
    cards.forEach((card, index) => {
      card.querySelector("[data-case-title]").textContent = `Test case ${index + 1}`;
      card.querySelector("[data-remove-case]").disabled = cards.length === 1;
    });
    try {
      const corpusVersionIds = [...selectedCorpus.keys()];
      const testCases = cards.map(caseValue);
      casesInput.value = JSON.stringify(testCases);
      corpusInput.value = JSON.stringify(corpusVersionIds);
      preview.textContent = JSON.stringify({ corpus_version_ids: corpusVersionIds, test_cases: testCases }, null, 2);
      error.textContent = "";
      error.hidden = true;
      return true;
    } catch (problem) {
      casesInput.value = "";
      corpusInput.value = "";
      preview.textContent = "JSON preview unavailable until the field is corrected.";
      error.textContent = problem.message;
      error.hidden = false;
      return false;
    }
  }

  function addCase() {
    const card = template.content.firstElementChild.cloneNode(true);
    card.querySelector("[data-remove-case]").addEventListener("click", () => {
      if (caseList.querySelectorAll("[data-case]").length > 1) {
        card.remove();
        refresh();
      }
    });
    caseList.append(card);
    refresh();
    return card;
  }

  form.querySelector("[data-add-case]").addEventListener("click", () => {
    addCase().querySelector('[data-field="question"]').focus();
  });
  form.querySelector("[data-add-template]").addEventListener("click", () => {
    const option = form.querySelector("[data-template-choice]").selectedOptions[0];
    if (!option || !option.value) return;
    const existing = [...caseList.querySelectorAll("[data-case]")];
    const first = existing[0];
    const card = existing.length === 1 && !field(first, "question").value.trim()
      ? first : addCase();
    field(card, "question").value = option.dataset.question;
    field(card, "answerability").value = option.dataset.answerability;
    field(card, "review_rubric").value = option.dataset.rubric;
    field(card, "tags").value = JSON.stringify({ scenario: option.dataset.tag });
    field(card, "relevance_complete").checked = false;
    field(card, "relevant_passage_ids").value = "";
    field(card, "question").focus();
    refresh();
  });
  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);
  tenantSelect.addEventListener("change", () => {
    updateUploadLink();
    loadDocuments(true);
  });
  // Choosing a document adds it straight away; there is no separate confirm step to miss.
  corpusChoice.addEventListener("change", (event) => {
    event.stopPropagation();
    addChosenDocument();
  });
  form.querySelector("[data-refresh-corpus]").addEventListener("click", () => loadDocuments(false));
  form.addEventListener("submit", (event) => {
    addChosenDocument();
    if (!refresh()) event.preventDefault();
    else if (selectedCorpus.size === 0) {
      event.preventDefault();
      error.textContent = "Add at least one activated document to the suite.";
      error.hidden = false;
    }
  });
  function fillCase(card, value) {
    field(card, "question").value = value.question || "";
    field(card, "authorized_identity_id").value = value.authorized_identity_id || "";
    field(card, "answerability").value = value.answerability || "answerable";
    field(card, "relevance_complete").checked = Boolean(value.relevance_complete);
    field(card, "relevant_passage_ids").value = (value.relevant_passage_ids || []).join("\n");
    field(card, "filter_text").value = value.filter_text || "";
    field(card, "expected_facts").value = value.expected_facts ? JSON.stringify(value.expected_facts, null, 2) : "";
    field(card, "review_rubric").value = value.review_rubric || "";
    field(card, "tags").value = JSON.stringify(value.tags || {});
  }

  let prefill = null;
  if (form.dataset.prefill) {
    try {
      prefill = JSON.parse(form.dataset.prefill);
    } catch {
      prefill = null;
    }
  }
  if (prefill && Array.isArray(prefill.test_cases) && prefill.test_cases.length) {
    for (const value of prefill.test_cases) fillCase(addCase(), value);
    for (const versionId of prefill.corpus_version_ids || []) {
      selectedCorpus.set(versionId, versionId.slice(0, 8));
    }
    refresh();
  } else {
    addCase();
  }
  updateUploadLink();
  loadDocuments(!prefill);
  const requestedTemplate = new URLSearchParams(window.location.search).get("template");
  if (requestedTemplate) {
    const choice = form.querySelector("[data-template-choice]");
    const matching = [...choice.options].find((option) => option.value === requestedTemplate);
    if (matching) {
      choice.value = requestedTemplate;
      form.querySelector("[data-add-template]").click();
    }
  }
}
