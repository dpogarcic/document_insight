"""Escaped server-rendered HTML for the private profile administration panel."""

import json
from datetime import UTC, datetime
from html import escape
from uuid import UUID

from document_insight.application.configuration.catalog import (
    CapabilityDetail,
    ProfileCatalog,
    QueryDetail,
)
from document_insight.application.configuration.models import Capability
from document_insight.application.evaluation.commands import EvaluationRunRecord
from document_insight.infrastructure.active_profile.protocol import ActiveProfile
from document_insight.infrastructure.capability_profile.protocol import CapabilityProfile
from document_insight.infrastructure.evaluation_case_result.protocol import EvaluationCaseResult
from document_insight.infrastructure.evaluation_case_template.protocol import EvaluationCaseTemplate
from document_insight.infrastructure.evaluation_gate_review.protocol import GateReview
from document_insight.infrastructure.evaluation_run.protocol import EvaluationRun
from document_insight.infrastructure.evaluation_suite.protocol import (
    EvaluationSuiteRevision,
)
from document_insight.infrastructure.ingestion_profile.protocol import IngestionProfile
from document_insight.infrastructure.tenant.protocol import TenantSummary


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def layout(title: str, content: str, *, notice: str | None = None, error: str | None = None) -> str:
    """Wrap escaped page content in the shared navigation and status shell."""
    alert = ""
    if notice:
        alert = f'<div class="notice" role="status">{_e(notice)}</div>'
    if error:
        alert = f'<div class="error" role="alert">{_e(error)}</div>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)} · Document Insight Admin</title><link rel="stylesheet" href="/static/admin.css"></head>
<body><header class="topbar"><a class="brand" href="/">Document Insight <span>Admin</span></a>
<nav aria-label="Main navigation"><a href="/">Overview</a><a href="/capabilities/new">New capability</a>
<a href="/ingestions/new">New ingestion policy</a><a href="/queries/new">New query policy</a>
<a href="/evaluations/suites">Evaluations</a></nav></header>
<main class="container">{alert}{content}</main><footer>Platform configuration · Operator access only</footer></body></html>"""


def _active_card(kind: str, active: ActiveProfile | None) -> str:
    if active is None:
        return f'<article class="card"><span class="eyebrow">{_e(kind)}</span><strong>Unavailable</strong></article>'
    href = f"/{'ingestions' if kind == 'Ingestion' else 'queries'}/{active.profile_id}"
    return f'<article class="card"><span class="eyebrow">Active {kind}</span><a class="strong" href="{href}">{_e(active.profile_id)}</a><small>Revision {_e(active.revision)}</small></article>'


def dashboard(catalog: ProfileCatalog) -> str:
    """Show the active pointers and reviewable profile inventories."""
    capabilities = (
        "".join(
            f'<tr><td><a href="/capabilities/{item.profile_id}">{_e(item.name or item.profile_id)}</a>'
            f'<small class="mono">{_e(item.profile_id)}</small></td><td>{_e(item.capability)}</td>'
            f'<td><span class="badge {"ready" if item.status == "validated" else "draft"}">{_e(item.status)}</span></td></tr>'
            for item in catalog.capabilities
        )
        or '<tr><td colspan="3">No capabilities yet.</td></tr>'
    )
    ingestions = (
        "".join(
            f'<tr><td><a href="/ingestions/{item.ingestion_profile_id}">{_e(item.ingestion_profile_id)}</a></td>'
            f"<td>{'Active' if catalog.active_ingestion and catalog.active_ingestion.profile_id == item.ingestion_profile_id else 'Available'}</td></tr>"
            for item in catalog.ingestions
        )
        or '<tr><td colspan="2">No ingestion policies yet.</td></tr>'
    )
    queries = (
        "".join(
            f'<tr><td><a href="/queries/{item.query_profile_id}">{_e(item.query_profile_id)}</a></td>'
            f"<td>{len(item.embedding_profile_ids)} embedding · {len(item.lexical_profile_ids)} lexical cohorts</td></tr>"
            for item in catalog.queries
        )
        or '<tr><td colspan="2">No query policies yet.</td></tr>'
    )
    return f"""
<section class="hero"><span class="eyebrow">Policy control</span><h1>Configuration profiles</h1>
<p>Review capability snapshots, approve drafts, and activate query and ingestion policies explicitly.</p></section>
<div class="card-grid">{_active_card("Ingestion", catalog.active_ingestion)}{_active_card("Query", catalog.active_query)}</div>
<div class="section-head"><h2>Capabilities</h2><a class="button secondary" href="/capabilities/new">Create capability</a></div>
<div class="table-wrap"><table><thead><tr><th>Profile</th><th>Capability</th><th>Status</th></tr></thead><tbody>{capabilities}</tbody></table></div>
<div class="section-head"><h2>Ingestion policies</h2><a class="button secondary" href="/ingestions/new">Create policy</a></div>
<div class="table-wrap"><table><thead><tr><th>Profile ID</th><th>State</th></tr></thead><tbody>{ingestions}</tbody></table></div>
<div class="section-head"><h2>Query policies</h2><a class="button secondary" href="/queries/new">Create policy</a></div>
<div class="table-wrap"><table><thead><tr><th>Profile ID</th><th>Read cohorts</th></tr></thead><tbody>{queries}</tbody></table></div>
"""


def capability_form(capability: Capability, template: dict[str, object], csrf: str) -> str:
    """Render a JSON editor for one immutable capability snapshot."""
    tabs = "".join(
        f'<a class="tab {"selected" if item == capability else ""}" href="/capabilities/new?capability={item.value}">{_e(item.value.title())}</a>'
        for item in Capability
    )
    return f"""<section class="hero compact"><span class="eyebrow">Step 1 · Draft</span><h1>New capability</h1>
<p>A draft cannot affect ingestion or queries. Review its configuration before validation.</p></section>
<div class="tabs">{tabs}</div><form method="post" action="/capabilities" class="panel form-stack">
<input type="hidden" name="csrf_token" value="{_e(csrf)}"><input type="hidden" name="capability" value="{_e(capability.value)}">
<label>Profile name<input name="name" maxlength="120" required placeholder="e.g. mistral-embed-v2"></label>
<label>Configuration JSON<textarea name="configuration_json" rows="17" spellcheck="false" required>{_e(json.dumps(template, indent=2, ensure_ascii=False))}</textarea></label>
<p class="hint">Store behavior settings here. Credentials and endpoint URLs belong in runtime configuration.</p>
<button class="button" type="submit">Create draft</button></form>"""


def capability_detail(detail: CapabilityDetail, csrf: str) -> str:
    """Show immutable configuration and the explicit validation action."""
    item = detail.profile
    action = (
        f'<form method="post" action="/capabilities/{item.profile_id}/validate">'
        f'<input type="hidden" name="csrf_token" value="{_e(csrf)}">'
        '<button class="button" type="submit">Validate and approve</button></form>'
        if item.status == "draft"
        else '<span class="badge ready">Approved for bundles</span>'
    )
    return f"""<section class="hero compact"><span class="eyebrow">{_e(item.capability)} · {_e(item.status)}</span>
<h1>{_e(item.name or item.profile_id)}</h1><p class="mono">{_e(item.profile_id)}</p></section>
<div class="panel"><h2>Immutable configuration</h2><pre>{_e(json.dumps(detail.configuration, indent=2, ensure_ascii=False))}</pre>
<div class="actions">{action}<a class="button secondary" href="/">Back to profiles</a></div></div>"""


def _select(
    name: str, label: str, choices: tuple[CapabilityProfile, ...], selected: UUID | None
) -> str:
    options = '<option value="">Select a validated profile</option>' + "".join(
        f'<option value="{item.profile_id}" {"selected" if item.profile_id == selected else ""}>'
        f"{_e(item.name or item.profile_id)} · {_e(item.profile_id)}</option>"
        for item in choices
    )
    return f'<label>{_e(label)}<select name="{_e(name)}" required>{options}</select></label>'


def ingestion_form(catalog: ProfileCatalog, csrf: str) -> str:
    """Offer only validated capability versions for the next ingestion bundle."""
    current = next(
        (
            item
            for item in catalog.ingestions
            if catalog.active_ingestion
            and item.ingestion_profile_id == catalog.active_ingestion.profile_id
        ),
        None,
    )
    selected = {
        "ner": None if current is None else current.ner_profile_id,
        "chunking": None if current is None else current.chunking_profile_id,
        "lexical": None if current is None else current.lexical_profile_id,
        "embedding": None if current is None else current.embedding_profile_id,
    }
    fields = "".join(
        _select(
            capability.value,
            capability.value.title(),
            tuple(
                item
                for item in catalog.capabilities
                if item.capability == capability.value and item.status == "validated"
            ),
            selected[capability.value],
        )
        for capability in (
            Capability.NER,
            Capability.CHUNKING,
            Capability.LEXICAL,
            Capability.EMBEDDING,
        )
    )
    return f"""<section class="hero compact"><span class="eyebrow">Step 2 · Bundle</span><h1>New ingestion policy</h1>
<p>New uploads use this bundle only after activation. Existing jobs retain the profile saved when they were created.</p></section>
<form class="panel form-stack" method="post" action="/ingestions"><input type="hidden" name="csrf_token" value="{_e(csrf)}">
{fields}<button class="button" type="submit">Create ingestion policy</button></form>"""


def _cohort_choices(
    name: str, choices: tuple[CapabilityProfile, ...], selected: tuple[UUID, ...]
) -> str:
    return (
        "".join(
            f'<label class="check"><input type="checkbox" name="{_e(name)}" value="{item.profile_id}" '
            f"{'checked' if item.profile_id in selected else ''}>"
            f'<span>{_e(item.name or item.profile_id)}<small class="mono">{_e(item.profile_id)}</small></span></label>'
            for item in choices
        )
        or '<p class="hint">No validated profiles available.</p>'
    )


def query_form(catalog: ProfileCatalog, retrieval: dict[str, object], csrf: str) -> str:
    """Show old and new read cohorts together so operators can preserve compatibility."""
    current = next(
        (
            item
            for item in catalog.queries
            if catalog.active_query and item.query_profile_id == catalog.active_query.profile_id
        ),
        None,
    )
    validated = tuple(item for item in catalog.capabilities if item.status == "validated")
    lexical = _cohort_choices(
        "lexical_ids",
        tuple(item for item in validated if item.capability == "lexical"),
        () if current is None else current.lexical_profile_ids,
    )
    embedding = _cohort_choices(
        "embedding_ids",
        tuple(item for item in validated if item.capability == "embedding"),
        () if current is None else current.embedding_profile_ids,
    )
    reranker = _select(
        "reranker",
        "Reranker",
        tuple(item for item in validated if item.capability == "reranking"),
        None if current is None else current.reranker_profile_id,
    )
    generation = _select(
        "generation",
        "Generation",
        tuple(item for item in validated if item.capability == "generation"),
        None if current is None else current.generation_profile_id,
    )
    return f"""<section class="hero compact"><span class="eyebrow">Step 2 · Bundle</span><h1>New query policy</h1>
<p>Keep earlier embedding and lexical cohorts selected while their ready indexes remain searchable.</p></section>
<form class="panel form-stack" method="post" action="/queries"><input type="hidden" name="csrf_token" value="{_e(csrf)}">
<div class="columns"><fieldset><legend>Lexical read cohorts</legend>{lexical}</fieldset>
<fieldset><legend>Embedding read cohorts</legend>{embedding}</fieldset></div>{reranker}{generation}
<label>Retrieval settings JSON<textarea name="retrieval_json" rows="12" spellcheck="false" required>{_e(json.dumps(retrieval, indent=2))}</textarea></label>
<button class="button" type="submit">Create query policy</button></form>"""


def _activation(kind: str, profile_id: UUID, active: ActiveProfile | None, csrf: str) -> str:
    if active is None:
        return '<p class="hint">No active pointer is available.</p>'
    if active.profile_id == profile_id:
        return '<span class="badge ready">Currently active</span>'
    return f"""<form class="activation" method="post" action="/profiles/{_e(kind)}/{profile_id}/activate">
<input type="hidden" name="csrf_token" value="{_e(csrf)}">
<input type="hidden" name="expected_revision" value="{_e(active.revision)}">
<label>Activation reason<input name="reason" maxlength="512" required placeholder="Why should this policy become active?"></label>
<p class="hint">Switches revision {_e(active.revision)} → {_e(active.revision + 1)}.
An approved <a href="/evaluations/suites">evaluation run</a> against the current baseline is required.</p>
<button class="button danger" type="submit">Activate {kind} policy</button></form>"""


def ingestion_detail(profile: IngestionProfile, active: ActiveProfile | None, csrf: str) -> str:
    """Show exact ingestion membership before activation."""
    items = (
        ("NER", profile.ner_profile_id),
        ("Chunking", profile.chunking_profile_id),
        ("Lexical", profile.lexical_profile_id),
        ("Embedding", profile.embedding_profile_id),
    )
    rows = "".join(
        f'<tr><th>{_e(label)}</th><td><a href="/capabilities/{identifier}">{_e(identifier)}</a></td></tr>'
        for label, identifier in items
    )
    return f"""<section class="hero compact"><span class="eyebrow">Ingestion policy</span><h1>Review bundle</h1>
<p class="mono">{_e(profile.ingestion_profile_id)}</p></section>
<div class="panel"><h2>Capability versions</h2><table class="detail-table"><tbody>{rows}</tbody></table>
<h2>Activation</h2><p>New uploads will use this policy. Existing jobs keep their stored policy.</p>
{_activation("ingestion", profile.ingestion_profile_id, active, csrf)}</div>"""


def query_detail(detail: QueryDetail, active: ActiveProfile | None, csrf: str) -> str:
    """Show compatible read cohorts and model settings before activation."""
    profile = detail.profile
    lexical = "".join(
        f'<li><a href="/capabilities/{item}">{_e(item)}</a></li>'
        for item in profile.lexical_profile_ids
    )
    embedding = "".join(
        f'<li><a href="/capabilities/{item}">{_e(item)}</a></li>'
        for item in profile.embedding_profile_ids
    )
    return f"""<section class="hero compact"><span class="eyebrow">Query policy</span><h1>Review bundle</h1>
<p class="mono">{_e(profile.query_profile_id)}</p></section><div class="panel">
<div class="columns"><div><h2>Lexical cohorts</h2><ul>{lexical}</ul></div><div><h2>Embedding cohorts</h2><ul>{embedding}</ul></div></div>
<h2>Model capabilities</h2><table class="detail-table"><tbody>
<tr><th>Reranker</th><td><a href="/capabilities/{profile.reranker_profile_id}">{_e(profile.reranker_profile_id)}</a></td></tr>
<tr><th>Generation</th><td><a href="/capabilities/{profile.generation_profile_id}">{_e(profile.generation_profile_id)}</a></td></tr>
</tbody></table><h2>Retrieval settings</h2><pre>{_e(json.dumps(detail.retrieval_configuration, indent=2))}</pre>
<h2>Activation</h2>{_activation("query", profile.query_profile_id, active, csrf)}</div>"""


# Evaluation views


def _tenant_label(tenant_id: UUID | None, tenant_names: dict[UUID, str]) -> str:
    """Show a suite's tenant name when known, falling back to the raw ID."""
    if tenant_id is None:
        return "—"
    return tenant_names.get(tenant_id, str(tenant_id))


def list_suites(
    suites: tuple[EvaluationSuiteRevision, ...],
    csrf: str,
    templates: tuple[EvaluationCaseTemplate, ...] = (),
    tenants: tuple[TenantSummary, ...] = (),
    selected_tenant_id: UUID | None = None,
) -> str:
    """Render one row per suite showing its latest version."""
    latest: dict[tuple[UUID | None, str], EvaluationSuiteRevision] = {}
    counts: dict[tuple[UUID | None, str], int] = {}
    for item in suites:
        key = (item.evaluation_tenant_id, item.suite_name)
        counts[key] = counts.get(key, 0) + 1
        if key not in latest or item.revision_number > latest[key].revision_number:
            latest[key] = item
    tenant_names = {tenant.tenant_id: tenant.name for tenant in tenants}
    rows = (
        "".join(
            f'<tr><td><a href="/evaluations/suites/{item.revision_id}">{_e(item.suite_name)}</a></td>'
            f"<td>{_e(_tenant_label(item.evaluation_tenant_id, tenant_names))}</td>"
            f"<td>v{_e(item.revision_number)}"
            f"{f' <small>{counts[key]} versions</small>' if counts[key] > 1 else ''}</td>"
            f"<td>{_e(len(item.test_cases))}</td>"
            f"<td>{_e(_when(item.created_at))}</td>"
            f'<td><a href="/evaluations/suites/{item.revision_id}/edit">Edit</a></td></tr>'
            for key, item in sorted(latest.items(), key=lambda pair: pair[1].suite_name.lower())
        )
        or '<tr><td colspan="6">No suites found.</td></tr>'
    )
    template_rows = (
        "".join(
            f"<tr><td>{_e(item.title)}</td><td>{_e(item.scenario_tag)}</td>"
            f"<td>{_e(item.answerability)}</td>"
            f'<td><a href="/evaluations/suites/new?template={_e(item.key)}{("&amp;tenant_id=" + str(selected_tenant_id)) if selected_tenant_id else ""}">Use in a suite</a></td></tr>'
            for item in templates
        )
        or '<tr><td colspan="4">No baseline scenarios are installed.</td></tr>'
    )

    return f"""
<section class="hero compact">
  <h1>Evaluation Suites</h1>
  <p>Test suites for evaluating retrieval and generation quality. Editing a suite saves a new version; past runs keep the version they used.</p>
</section>
<div class="suite-index">
<form class="panel form-stack" method="get" action="/evaluations/suites">
  <label>Tenant<select name="tenant_id"><option value="">All tenants</option>
  {"".join(f'<option value="{_e(t.tenant_id)}" {"selected" if t.tenant_id == selected_tenant_id else ""}>{_e(t.name)}</option>' for t in tenants)}
  </select></label><button class="button secondary" type="submit">Show suites</button>
</form>
<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Suite</th>
        <th>Tenant</th>
        <th>Version</th>
        <th>Cases</th>
        <th>Last saved</th>
        <th></th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>
<div class="actions">
  <a class="button secondary" href="/evaluations/suites/new{("?tenant_id=" + str(selected_tenant_id)) if selected_tenant_id else ""}">Create Suite</a>
  <a class="button secondary" href="/evaluations/corpus">Test corpus setup</a>
</div>
<section class="panel">
  <h2>Baseline scenarios</h2>
  <p class="hint">Reusable starting points. Choose one, then select a corpus, identity, and source labels before running an evaluation.</p>
  <div class="table-wrap"><table>
    <thead><tr><th>Scenario</th><th>Coverage</th><th>Answerability</th><th></th></tr></thead>
    <tbody>{template_rows}</tbody>
  </table></div>
</section>
</div>
"""


def evaluation_corpus_setup(
    tenant_id: UUID | None,
    catalog: ProfileCatalog,
    selected: ActiveProfile | None,
    csrf: str,
    upload_url: str = "/evaluation-corpus/upload",
) -> str:
    """Explain the isolated ingestion selection and offer reviewed policy choices."""
    options = "".join(
        f'<option value="{item.ingestion_profile_id}">{_e(item.ingestion_profile_id)}</option>'
        for item in catalog.ingestions
    )
    return f'''<section class="hero compact"><h1>Evaluation corpus</h1>
<p>Dedicated test tenant: <span class="mono">{_e(tenant_id or "Not configured")}</span></p>
<p>Selected ingestion policy for new test-tenant uploads:
<span class="mono">{_e(selected.profile_id if selected else "Platform default")}</span></p></section>
<form class="panel form-stack" method="post" action="/evaluations/corpus/ingestion">
<h2>Select test ingestion policy</h2>
<input type="hidden" name="csrf_token" value="{_e(csrf)}">
<input type="hidden" name="expected_revision" value="{_e(selected.revision if selected else 0)}">
<label>Ingestion policy<select name="profile_id" required>{options}</select></label>
<label>Reason<input name="reason" maxlength="512" required></label>
<button class="button" type="submit">Use for new test uploads</button></form>
<div class="panel"><h2>Prepare a comparison corpus</h2>
<p>Upload each source document as a separate new document through the authenticated API using
a test-tenant editor or admin. Process and activate those test copies, then map their version IDs
to the suite source IDs when launching an ingestion evaluation.</p>
<a class="button secondary" href="{_e(upload_url)}" target="_blank" rel="noopener">Upload test documents</a></div>'''


def suite_prefill(suite: EvaluationSuiteRevision) -> dict[str, object]:
    """Express a saved revision in the same shape the suite form submits."""
    return {
        "corpus_version_ids": [str(value) for value in suite.corpus_version_ids],
        "test_cases": [
            {
                "question": case.question,
                "authorized_identity_id": str(case.authorized_identity_id),
                "answerability": str(getattr(case.answerability, "value", case.answerability)),
                "relevance_complete": case.relevance_complete,
                "relevant_passage_ids": list(case.relevant_passage_ids),
                "filter_text": case.filter_text,
                "expected_facts": case.expected_facts,
                "review_rubric": case.review_rubric,
                "tags": dict(case.tags or {}),
            }
            for case in sorted(suite.test_cases, key=lambda item: item.sort_order)
        ],
    }


def suite_form(
    csrf: str,
    templates: tuple[EvaluationCaseTemplate, ...] = (),
    upload_url: str = "/evaluation-corpus/upload",
    tenants: tuple[TenantSummary, ...] = (),
    selected_tenant_id: UUID | None = None,
    editing: EvaluationSuiteRevision | None = None,
) -> str:
    """Render fixed case fields and a read-only JSON representation.

    With ``editing``, the form opens pre-filled from that revision and saving it
    creates the suite's next revision; the edited revision and its runs stay unchanged.
    """
    template_options = "".join(
        f'<option value="{_e(item.key)}" data-question="{_e(item.question)}" '
        f'data-answerability="{_e(item.answerability)}" '
        f'data-rubric="{_e(item.review_rubric)}" '
        f'data-tag="{_e(item.scenario_tag)}">{_e(item.title)}</option>'
        for item in templates
    )
    if editing is None:
        hero = """<section class="hero compact">
  <h1>Create Evaluation Suite</h1>
  <p>Choose the document versions to test, then define the questions and evidence you expect. Saving does not start a run.</p>
</section>"""
        tenant_field = f"""<label>Tenant
    <small>Suite and selected documents belong to this tenant. Each case runs with the current access of a user in this tenant.</small>
    <select name="tenant_id" required><option value="">Choose a tenant</option>
    {"".join(f'<option value="{_e(t.tenant_id)}" {"selected" if t.tenant_id == selected_tenant_id else ""}>{_e(t.name)}</option>' for t in tenants)}
    </select>
  </label>"""
        name_field = """<label>Suite name
    <small>A readable label for this group of cases.</small>
    <input type="text" name="suite_name" maxlength="200" required
           placeholder="e.g. retrieval-quality-baseline">
  </label>"""
        edit_fields = ""
        prefill = ""
        submit_label = "Create Suite"
        cancel_url = "/evaluations/suites"
    else:
        tenant_name = next(
            (t.name for t in tenants if t.tenant_id == editing.evaluation_tenant_id),
            str(editing.evaluation_tenant_id),
        )
        hero = f"""<section class="hero compact">
  <span class="eyebrow">Edit suite</span>
  <h1>{_e(editing.suite_name)}</h1>
  <p>Editing version {_e(editing.revision_number)}. Saving creates version {_e(editing.revision_number + 1)}; runs already made keep the cases and documents they were scored against.</p>
</section>"""
        # A one-option select keeps the tenant fixed while the form script reads it as usual.
        tenant_field = f"""<label>Tenant
    <small>A suite stays with its tenant. Create a new suite to test another tenant.</small>
    <select name="tenant_id" required><option value="{_e(editing.evaluation_tenant_id)}" selected>{_e(tenant_name)}</option></select>
  </label>"""
        name_field = f"""<label>Suite name
    <small>The name identifies the suite, so it stays the same across versions.</small>
    <input type="text" name="suite_name" maxlength="200" required readonly value="{_e(editing.suite_name)}">
  </label>"""
        edit_fields = (
            f'<input type="hidden" name="base_revision_id" value="{_e(editing.revision_id)}">'
        )
        prefill = f' data-prefill="{_e(json.dumps(suite_prefill(editing)))}"'
        submit_label = "Save changes"
        cancel_url = f"/evaluations/suites/{editing.revision_id}"
    return f"""
{hero}
<form method="post" action="/evaluations/suites" class="panel form-stack" data-suite-form{prefill}>
  <input type="hidden" name="csrf_token" value="{_e(csrf)}">
  <input type="hidden" name="test_cases_json" value="">
  <input type="hidden" name="corpus_version_ids_json" value="">
  {edit_fields}
  {tenant_field}
  {name_field}
  <section class="scenario-picker">
    <h2>Need test documents?</h2>
    <p class="hint">Upload and activate them with a user from the selected tenant. Return here and refresh the list when processing is complete.</p>
    <a class="button secondary" href="{_e(upload_url)}" data-upload-link data-base-url="{_e(upload_url)}" target="_blank" rel="noopener">Upload test documents</a>
  </section>
  <section class="scenario-picker corpus-picker" aria-labelledby="corpus-picker-title">
    <h2 id="corpus-picker-title">Documents to evaluate</h2>
    <p class="hint">Choose activated documents from the selected tenant. Each document you choose is added to the list below; every case runs against the same selection.</p>
    <label>Activated document version
      <select data-corpus-choice disabled><option value="">Choose a tenant first</option></select>
    </label>
    <div class="actions">
      <button class="button secondary" type="button" data-refresh-corpus>Refresh documents</button>
    </div>
    <p class="hint" data-corpus-status role="status">Choose a tenant to see its activated documents.</p>
    <ul class="corpus-selected" data-corpus-selected aria-label="Selected documents"></ul>
  </section>
  <section class="scenario-picker">
    <h2>Baseline scenarios</h2>
    <p class="hint">Add a starting question, then replace bracketed text and set its identity and evidence labels for this corpus.</p>
    <label>Scenario to add<select data-template-choice><option value="">Choose a scenario</option>{template_options}</select></label>
    <button class="button secondary" type="button" data-add-template>Add scenario</button>
  </section>
  <div data-case-list></div>
  <div class="actions"><button class="button secondary" type="button" data-add-case>Add test case</button></div>
  <details class="json-preview">
    <summary>Show saved case data</summary>
    <p class="hint">Read-only preview of the data this form will save.</p>
    <pre data-json-preview aria-live="polite"></pre>
  </details>
  <p class="error" data-form-error hidden role="alert"></p>
  <div class="form-actions">
    <button class="button" type="submit">{submit_label}</button>
    <a class="button secondary" href="{_e(cancel_url)}">Cancel</a>
  </div>
</form>
<template data-case-template>
  <fieldset class="case-card" data-case>
    <legend data-case-title>Test case</legend>
    <div class="case-fields">
      <label class="wide-field">Question
        <small>The exact question sent to both the baseline and candidate query policies.</small>
        <textarea data-field="question" rows="3" required></textarea></label>
      <label>Test identity UUID
        <small>A current user in the selected tenant whose access rules apply. The first case must use a tenant admin.</small>
        <input data-field="authorized_identity_id" type="text" required></label>
      <label>Expected answerability
        <small>Can this identity answer from the selected corpus? Used to score correct answers versus refusals.</small>
        <select data-field="answerability"><option value="answerable">Answerable</option><option value="unanswerable">Unanswerable</option></select></label>
      <label class="wide-field">Relevant source spans
        <small>Passages that support the answer, one per line as version UUID@page:start:end. Used for retrieval and citation scores; leave blank for unanswerable cases.</small>
        <textarea data-field="relevant_passage_ids" rows="3" spellcheck="false"></textarea></label>
      <label class="check wide-field"><input data-field="relevance_complete" type="checkbox"><span>These are all relevant spans
        <small>Check only when you labelled every relevant passage. This enables recall scores; partial labels still support precision scores.</small></span></label>
      <label class="wide-field">Query filter
        <small>Optional text used by entity matching and lexical search. It cannot expand the test identity’s access.</small>
        <input data-field="filter_text" type="text"></label>
      <label class="wide-field">Expected facts
        <small>Optional JSON object for reviewers, such as {{"date":"2026-09-23"}}. Saved with the case; answer quality is scored manually.</small>
        <textarea data-field="expected_facts" rows="3" spellcheck="false" placeholder='{{"fact":"expected value"}}'></textarea></label>
      <label class="wide-field">Review rubric
        <small>Optional instructions for the operator who scores the generated answer after a run.</small>
        <textarea data-field="review_rubric" rows="3"></textarea></label>
      <label class="wide-field">Tags
        <small>Optional JSON string pairs to identify the scenario. Tags do not change the question or scoring.</small>
        <textarea data-field="tags" rows="3" spellcheck="false">{{}}</textarea></label>
    </div>
    <div class="case-actions"><button class="button secondary" type="button" data-remove-case>Remove case</button></div>
  </fieldset>
</template>
<script src="/static/evaluation_suite_form.js" defer></script>
"""


def suite_detail(
    suite: EvaluationSuiteRevision,
    csrf: str,
    catalog: ProfileCatalog,
    *,
    allow_ingestion: bool = True,
    revisions: tuple[EvaluationSuiteRevision, ...] = (),
) -> str:
    """Render suite revision detail with its edit action and version history."""
    history = sorted(revisions or (suite,), key=lambda item: item.revision_number, reverse=True)
    latest = history[0] if history else suite
    is_latest = latest.revision_number <= suite.revision_number
    if is_latest:
        version_note = (
            f'<a class="button" href="/evaluations/suites/{suite.revision_id}/edit">Edit suite</a>'
        )
    else:
        version_note = (
            f'<div class="notice" role="status">You are viewing version {_e(suite.revision_number)}. '
            f"The latest is version {_e(latest.revision_number)}. "
            f'<a href="/evaluations/suites/{latest.revision_id}">Open the latest version</a> to edit it.</div>'
        )
    history_items = "".join(
        f'<li class="{"current" if item.revision_id == suite.revision_id else ""}">'
        f'<a href="/evaluations/suites/{item.revision_id}">Version {_e(item.revision_number)}</a>'
        f' <span class="hint">{_e(len(item.test_cases))} case{"" if len(item.test_cases) == 1 else "s"}'
        f" · {_e(_when(item.created_at))}</span>"
        + (
            ' <span class="badge pending">viewing</span>'
            if item.revision_id == suite.revision_id
            else ""
        )
        + "</li>"
        for item in history
    )
    cases = (
        "".join(
            f"<tr><td>{_e(case.question[:100])}...</td>"
            f"<td>{_e(case.answerability)}</td>"
            f"<td>{_e(case.tags)}</td>"
            f"<td>{len(case.relevant_passage_ids)} passages</td></tr>"
            for case in suite.test_cases
        )
        or '<tr><td colspan="4">No test cases.</td></tr>'
    )

    return f"""
<section class="hero compact">
  <span class="eyebrow">Evaluation suite</span>
  <h1>{_e(suite.suite_name)} <span class="muted">v{_e(suite.revision_number)}</span></h1>
  <p class="mono">{_e(suite.revision_id)}</p>
  <div class="actions">{version_note}</div>
</section>
<div class="panel">
  <h2>Test Cases ({len(suite.test_cases)})</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>Question</th><th>Answerability</th><th>Tags</th><th>Relevant Passages</th></tr>
      </thead>
      <tbody>{cases}</tbody>
    </table>
  </div>
  <p><strong>Tenant:</strong> {_e(suite.evaluation_tenant_id)}</p>
  <p><strong>Corpus fingerprint:</strong> <span class="mono">{_e(suite.dataset_fingerprint)}</span></p>
  <div class="actions">
    <a class="button secondary" href="/evaluations/suites">Back to Suites</a>
  </div>
</div>
<section class="panel suite-history">
  <h2>Versions</h2>
  <p class="hint">Editing saves a new version. Each run keeps the version it was scored against.</p>
  <ul>{history_items}</ul>
</section>
<form class="panel form-stack" method="post" action="/evaluations/runs">
<h2>Run against a proposed query policy</h2>
<input type="hidden" name="csrf_token" value="{_e(csrf)}">
<input type="hidden" name="suite_revision_id" value="{_e(suite.revision_id)}">
<input type="hidden" name="evaluation_mode" value="query">
<p>Baseline: {_e(catalog.active_query.profile_id if catalog.active_query else "No active query policy")}</p>
<label>Candidate query policy<select name="candidate_profile_id" required>
{"".join(f'<option value="{item.query_profile_id}">{_e(item.query_profile_id)}</option>' for item in catalog.selectable_queries if catalog.active_query is None or item.query_profile_id != catalog.active_query.profile_id)}
</select></label>
<label>K values (JSON array)<input name="k_values_json" value="[1, 5, 10]" required></label>
<button class="button" type="submit">Run evaluation</button></form>
{_ingestion_form(suite, csrf, catalog) if allow_ingestion else '<p class="hint">Ingestion comparisons use the isolated test tenant; query comparisons can use this tenant’s selected documents.</p>'}
"""


def _ingestion_form(suite: EvaluationSuiteRevision, csrf: str, catalog: ProfileCatalog) -> str:
    """Render the test-tenant-only ingestion comparison controls."""
    return f"""<form class="panel form-stack" method="post" action="/evaluations/runs">
<h2>Compare an ingestion policy on copied test documents</h2>
<input type="hidden" name="csrf_token" value="{_e(csrf)}">
<input type="hidden" name="suite_revision_id" value="{_e(suite.revision_id)}">
<input type="hidden" name="evaluation_mode" value="ingestion">
<p>Baseline ingestion policy: {_e(catalog.active_ingestion.profile_id if catalog.active_ingestion else "Unavailable")}</p>
<label>Candidate ingestion policy<select name="candidate_ingestion_profile_id" required>
{"".join(f'<option value="{item.ingestion_profile_id}">{_e(item.ingestion_profile_id)}</option>' for item in catalog.ingestions)}
</select></label>
<p>Active query policy reading both cohorts: {_e(catalog.active_query.profile_id if catalog.active_query else "Unavailable")}</p>
<input type="hidden" name="candidate_profile_id" value="{_e(catalog.active_query.profile_id if catalog.active_query else "")}">
<label>Source to candidate version IDs (JSON object)
<textarea name="candidate_version_mapping_json" rows="6" required placeholder='{{"source-version-uuid":"candidate-version-uuid"}}'></textarea></label>
<label>K values (JSON array)<input name="k_values_json" value="[1, 5, 10]" required></label>
<button class="button" type="submit">Compare ingestion policies</button></form>
"""


def list_runs(records: tuple[EvaluationRunRecord, ...], csrf: str) -> str:
    """Render a list of evaluation runs."""
    rows = (
        "".join(
            f'<tr><td><a href="/evaluations/runs/{item.run_id}">{_e(item.run_id)}</a></td>'
            f"<td>{_e(item.tenant_id or '—')}</td>"
            f"<td>{_e(item.suite_name)}</td>"
            f"<td>{_e(item.status)}</td>"
            f"<td>{_e(item.case_count)} cases</td>"
            f"<td>{_e(item.completed_case_count)} done</td>"
            f"<td>{_e(item.started_at or '—')}</td>"
            f"<td>{_e(item.completed_at or '—')}</td></tr>"
            for item in records
        )
        or '<tr><td colspan="8">No runs found.</td></tr>'
    )

    return f"""
<section class="hero compact">
  <h1>Evaluation Runs</h1>
  <p>Execution records with per-case results and aggregate measurements.</p>
</section>
<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Run ID</th>
        <th>Tenant</th>
        <th>Suite</th>
        <th>Status</th>
        <th>Cases</th>
        <th>Completed</th>
        <th>Started</th>
        <th>Completed</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>
<div class="actions">
  <a class="button secondary" href="/evaluations/suites">Back to Suites</a>
</div>
"""


_BADGE_TONES = {
    "completed": "success",
    "answered": "success",
    "approve": "success",
    "failed": "danger",
    "reject": "danger",
    "error": "danger",
}


def _when(value: object) -> str:
    """Show stored ISO timestamps as a short UTC time; leave anything else untouched."""
    if not value:
        return "—"
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%d %H:%M:%S") + (" UTC" if moment.tzinfo is not None else "")


def _badge(value: object) -> str:
    text = str(value) if value not in (None, "") else "—"
    tone = _BADGE_TONES.get(text.lower(), "pending")
    return f'<span class="badge {tone}">{_e(text)}</span>'


def _run_variant(
    item: EvaluationCaseResult, record: EvaluationRunRecord, csrf: str, can_review: bool
) -> str:
    """One variant's answer, citations, trace, and manual score for a single case."""
    citations = [
        str(c.get("source_anchor", "")) for c in item.final_citations if c.get("source_anchor")
    ]
    citation_list = (
        '<ul class="citation-list">'
        + "".join(f'<li class="mono">{_e(c)}</li>' for c in citations)
        + "</ul>"
        if citations
        else '<p class="hint">No citations.</p>'
    )
    trace = json.dumps(
        {
            "measurements": item.measurements,
            "lexical": item.lexical_cohort_ranked_ids,
            "vector": item.vector_cohort_ranked_ids,
            "fused": item.fused_ranked_ids,
            "reranked": item.reranked_ranked_ids,
            "latency_ms": item.stage_latencies_ms,
            "provider_errors": item.provider_errors,
        },
        indent=2,
        default=str,
    )
    if item.answer_quality_score is not None:
        note = f" · {_e(item.answer_quality_note)}" if item.answer_quality_note else ""
        quality = f'<p class="quality-score"><strong>Manual quality:</strong> {_e(item.answer_quality_score)}{note}</p>'
    elif can_review:
        quality = (
            f'<form class="quality-form" method="post" action="/evaluations/runs/{record.run_id}/cases/{item.result_id}/quality">'
            f'<input type="hidden" name="csrf_token" value="{_e(csrf)}">'
            '<label>Score (0–1)<input type="number" name="score" min="0" max="1" step="0.1" required></label>'
            '<label>Reason<input name="note" maxlength="2000" placeholder="Why this score?"></label>'
            '<button class="button" type="submit">Save score</button></form>'
        )
    else:
        quality = '<p class="hint">Not scored.</p>'
    answer = (
        f'<div class="answer-text">{_e(item.answer_text)}</div>'
        if item.answer_text
        else '<p class="hint">No answer returned.</p>'
    )
    return f"""<section class="variant variant-{_e(item.variant)}">
  <header class="variant-head"><h4>{_e(item.variant.title())}</h4>{_badge(item.status.value)}</header>
  <p class="variant-outcome"><span class="eyebrow">Answer outcome</span>{_badge(item.answerability_outcome)}</p>
  <span class="eyebrow">Answer</span>{answer}
  <span class="eyebrow">Citations</span>{citation_list}
  <details class="trace"><summary>Case metrics and rankings</summary><pre>{_e(trace)}</pre></details>
  {quality}
</section>"""


def run_detail(
    record: EvaluationRunRecord,
    csrf: str,
    run: EvaluationRun | None,
    review: GateReview | None,
    suite: EvaluationSuiteRevision | None = None,
) -> str:
    """Render run detail with baseline and candidate results side by side per case."""
    by_metric = (
        {}
        if run is None
        else {
            (item.stage, item.metric_name, item.k, item.cohort_id, item.variant): item
            for item in run.aggregate_measurements
        }
    )
    metric_keys = {(stage, name, k, cohort) for stage, name, k, cohort, _ in by_metric}
    metrics = "".join(
        f"<tr><td>{_e(stage)}</td><td>{_e(name)}{f'@{k}' if k else ''}</td>"
        f"<td>{_e(cohort or 'all')}</td>"
        f'<td class="num">{_e(f"{baseline.metric_value:.3f}" if baseline else "—")}</td>'
        f'<td class="num">{_e(f"{candidate.metric_value:.3f}" if candidate else "—")}</td>'
        f'<td class="num">{_e(f"{candidate.metric_value - baseline.metric_value:+.3f}" if baseline and candidate else "—")}</td>'
        f'<td class="num">{_e(f"{candidate.numerator}/{candidate.denominator}" if candidate else "—")}</td></tr>'
        for stage, name, k, cohort in sorted(
            metric_keys, key=lambda item: (item[0], item[1], item[2] or 0, str(item[3]))
        )
        for baseline in (by_metric.get((stage, name, k, cohort, "baseline")),)
        for candidate in (by_metric.get((stage, name, k, cohort, "candidate")),)
    )
    metrics_table = (
        '<div class="table-wrap"><table class="metrics-table"><thead><tr><th>Stage</th><th>Metric</th>'
        '<th>Cohort</th><th class="num">Baseline</th><th class="num">Candidate</th><th class="num">Change</th>'
        f'<th class="num">Candidate counts</th></tr></thead><tbody>{metrics}</tbody></table></div>'
        if metrics
        else '<p class="hint">No aggregate measurements yet.</p>'
    )

    labels = {} if suite is None else {item.case_id: item for item in suite.test_cases}
    can_review = record.status == "completed" and review is None
    grouped: dict[UUID, list[EvaluationCaseResult]] = {}
    for item in () if run is None else run.per_case_results:
        grouped.setdefault(item.case_id, []).append(item)
    variant_order = {"baseline": 0, "candidate": 1}
    case_cards = []
    for number, (case_id, items) in enumerate(grouped.items(), start=1):
        case = labels.get(case_id)
        items.sort(key=lambda result: variant_order.get(result.variant, 2))
        if case is not None:
            facts = (
                f"<pre>{_e(json.dumps(case.expected_facts, indent=2))}</pre>"
                if case.expected_facts
                else '<p class="hint">None.</p>'
            )
            passages = ", ".join(case.relevant_passage_ids) or "—"
            label_block = f"""<details class="case-labels"><summary>Approved labels and rubric</summary>
  <dl class="meta-list">
    <dt>Answerability</dt><dd>{_e(case.answerability.value)}</dd>
    <dt>Relevant passages</dt><dd class="mono">{_e(passages)}</dd>
    <dt>Review rubric</dt><dd>{_e(case.review_rubric or "—")}</dd>
    <dt>Expected facts</dt><dd>{facts}</dd>
  </dl></details>"""
            question = _e(case.question)
        else:
            label_block = ""
            question = "Question unavailable"
        variants = "".join(_run_variant(item, record, csrf, can_review) for item in items)
        case_cards.append(
            f"""<article class="case-result">
  <header class="case-result-head"><span class="eyebrow">Case {number}</span>
  <h3>{question}</h3><small class="mono">{_e(case_id)}</small></header>
  {label_block}
  <div class="variant-grid">{variants}</div>
</article>"""
        )
    cases = "".join(case_cards) or '<p class="hint">No case results yet.</p>'

    if review:
        gate = (
            f'<p>{_badge(review.decision)} <span class="hint">{_e(_when(review.created_at))}</span></p>'
            f"<p>{_e(review.reason)}</p>"
        )
    else:
        gate = '<p class="hint">Awaiting operator review.</p>'
    review_form = ""
    if can_review:
        review_form = f'''<form class="panel form-stack" method="post" action="/evaluations/runs/{record.run_id}/review">
<h2>Manual quality gate</h2><input type="hidden" name="csrf_token" value="{_e(csrf)}">
<label>Decision<select name="decision"><option value="approve">Approve</option><option value="reject">Reject</option></select></label>
<label>Reason<textarea name="reason" maxlength="1000" required></textarea></label>
<button class="button" type="submit">Record decision</button></form>'''

    def _ids(values: tuple[UUID, ...]) -> str:
        return "".join(f'<li class="mono">{_e(value)}</li>' for value in values) or "<li>—</li>"

    fingerprints = (
        "".join(
            f'<dt>{_e(name.replace("_", " "))} fingerprint</dt><dd class="mono">{_e(value)}</dd>'
            for name, value in sorted((record.config_fingerprints or {}).items())
        )
        or "<dt>Fingerprints</dt><dd>—</dd>"
    )
    error = (
        f'<div class="error" role="alert">{_e(record.error_message)}</div>'
        if record.error_message
        else ""
    )
    return f"""
<div class="run-page">
<section class="hero compact">
  <span class="eyebrow">Evaluation run</span>
  <h1>{_e(record.suite_name)} <span class="muted">v{_e(record.revision_number)}</span></h1>
  <p class="mono run-id">{_e(record.run_id)}</p>
</section>
{error}
<div class="card-grid run-summary">
  <div class="card"><span class="eyebrow">Status</span>{_badge(record.status)}</div>
  <div class="card"><span class="eyebrow">Cases</span><span><strong>{_e(record.completed_case_count)}</strong> of {_e(record.case_count)} completed</span></div>
  <div class="card"><span class="eyebrow">Started</span><span class="mono">{_e(_when(record.started_at))}</span></div>
  <div class="card"><span class="eyebrow">Completed</span><span class="mono">{_e(_when(record.completed_at))}</span></div>
</div>
<section class="panel">
  <h2>Gate review</h2>
  {gate}
</section>
<section class="panel">
  <h2>Aggregate metrics</h2>
  {metrics_table}
</section>
<section class="run-cases">
  <div class="section-head"><h2>Case results</h2><span class="hint">Baseline and candidate side by side</span></div>
  {cases}
</section>
{review_form}
<details class="panel run-config">
  <summary><h2>Profile configuration</h2></summary>
  <dl class="meta-list">
    <dt>Baseline profiles</dt><dd><ul class="id-list">{_ids(record.baseline_profile_ids)}</ul></dd>
    <dt>Candidate profiles</dt><dd><ul class="id-list">{_ids(record.candidate_profile_ids)}</ul></dd>
    <dt>K values</dt><dd>{_e(", ".join(str(k) for k in record.k_values) or "—")}</dd>
    {fingerprints}
  </dl>
</details>
<div class="actions"><a class="button secondary" href="/evaluations/runs">Back to runs</a></div>
</div>
"""
