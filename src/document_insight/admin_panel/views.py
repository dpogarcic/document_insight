"""Escaped server-rendered HTML for the private profile administration panel."""

import json
from html import escape
from uuid import UUID

from document_insight.application.configuration.catalog import (
    CapabilityDetail,
    ProfileCatalog,
    QueryDetail,
)
from document_insight.application.configuration.models import Capability
from document_insight.infrastructure.active_profile.protocol import ActiveProfile
from document_insight.infrastructure.capability_profile.protocol import CapabilityProfile
from document_insight.infrastructure.ingestion_profile.protocol import IngestionProfile


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
<a href="/ingestions/new">New ingestion policy</a><a href="/queries/new">New query policy</a></nav></header>
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
<p class="hint">Switches revision {_e(active.revision)} → {_e(active.revision + 1)}. Review the cohorts before activating.</p>
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
