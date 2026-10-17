"""Fictional, source-backed Meridian facts; no production company data."""

SEED_VERSION = 1

SAMPLE_UPDATED_AT = "2026-10-15T09:00:00+00:00"


def source(source_id, title, kind, excerpt, author):
    return {"id": source_id, "title": title, "type": kind, "excerpt": excerpt,
            "updated_at": SAMPLE_UPDATED_AT, "author": author}


SOURCES = [
    source("src-launch-brief", "Atlas launch brief", "document",
           "FICTIONAL MERIDIAN SAMPLE. Atlas launches on October 23. Mara Chen owns launch readiness. "
           "Atlas depends on Checkout, Public API, Analytics pipeline, Launch docs, and Rollout flags. "
           "The launch is at risk if any required dependency is unavailable; this is exposure, not a "
           "probability forecast. Launch documentation must be reviewed before the release.", "Mara Chen"),
    source("src-payment-runbook", "Payments continuity runbook", "document",
           "FICTIONAL MERIDIAN SAMPLE. Checkout depends on Payment gateway, owned by Devon Park. "
           "Checkout can use Backup provider if Devon validates the failover checklist and sample "
           "transactions. Backup provider supports checkout authorization only. The backup does not "
           "cover Billing reconciliation or erase the Payment gateway outage. Checkout also depends "
           "on Identity service. The backup assumption is hypothetical until the owner validates it.", "Devon Park"),
    source("src-payment-incident", "INC-042 · Payment provider timeout", "incident",
           "FICTIONAL MERIDIAN SAMPLE. On September 18, payment timeouts blocked Checkout. Devon Park "
           "switched checkout authorization to Backup provider after a controlled transaction test; "
           "checkout recovered in 18 minutes. Billing reconciliation remained delayed until the "
           "primary provider recovered. This incident supports the narrow checkout failover path, "
           "not a guarantee of the same recovery time in a new incident.", "Devon Park"),
    source("src-backup-decision", "ADR-017 · Checkout fallback provider", "decision",
           "FICTIONAL MERIDIAN SAMPLE. Backup provider is approved as an alternative to Payment gateway "
           "for Checkout authorization. It is not approved for Billing reconciliation. Activation "
           "requires Devon Park's transaction validation and Mara Chen's launch-readiness review.", "Mara Chen"),
    source("src-api-contract", "Atlas API release contract", "code",
           "FICTIONAL MERIDIAN SAMPLE. Public API is owned by Alex Rivera and the Platform team. "
           "It depends on Identity service. API contract tests must pass for the Atlas launch.", "Alex Rivera"),
    source("src-analytics-plan", "Launch measurement plan", "document",
           "FICTIONAL MERIDIAN SAMPLE. Analytics pipeline is owned by Priya Shah and the Data team. "
           "It depends on Public API for event ingestion. Atlas launch readiness includes event "
           "delivery verification and a dashboard review.", "Priya Shah"),
    source("src-release-checklist", "Atlas release checklist", "ticket",
           "FICTIONAL MERIDIAN SAMPLE. Mara Chen owns Launch docs and Rollout flags. Launch docs "
           "depend on the API contract document. The checklist records owner sign-off for Checkout, "
           "Public API, Analytics pipeline, Launch docs, and Rollout flags. No live rollout has run.", "Mara Chen"),
    source("src-team-roster", "Meridian ownership roster", "document",
           "FICTIONAL MERIDIAN SAMPLE. Product: Mara Chen, Atlas launch, Launch docs, Rollout flags. "
           "Platform: Devon Park, payments, backup and billing; Alex Rivera, Public API and Identity "
           "service. Data: Priya Shah, Analytics pipeline. Owners are accountable for validation "
           "and readiness decisions; Relay tasks are internal proposals.", "Mara Chen"),
    source("src-billing-policy", "Settlement and reconciliation dependency", "document",
           "FICTIONAL MERIDIAN SAMPLE. Billing reconciliation depends directly on Payment gateway's "
           "settlement export. The approved Backup provider cannot produce this export. An outage "
           "therefore leaves billing exposed even if Checkout fails over. Devon Park owns recovery.", "Devon Park"),
    source("src-auth-contract", "Identity service contract", "code",
           "FICTIONAL MERIDIAN SAMPLE. Identity service is owned by Alex Rivera. Checkout and Public "
           "API depend on its token validation. The payment backup does not mitigate identity failure.", "Alex Rivera"),
]


def node(node_id, label, kind, description, x, y, sources, owner=None, status="healthy"):
    result = {"id": node_id, "label": label, "kind": kind, "description": description,
              "status": status, "source_ids": sources, "x": x, "y": y}
    if owner:
        result["owner"] = owner
    return result


NODES = [
    node("payment-gateway", "Payment gateway", "service", "Primary authorization and settlement provider.",
         110, 240, ["src-payment-runbook", "src-billing-policy"], "Devon Park"),
    node("checkout", "Checkout", "service", "Atlas purchase flow; a required launch dependency.",
         420, 230, ["src-payment-runbook", "src-launch-brief"], "Devon Park"),
    node("atlas-launch", "Atlas launch", "project", "Meridian's October 23 launch readiness graph.",
         760, 245, ["src-launch-brief"], "Mara Chen", "active"),
    node("backup-provider", "Backup provider", "service", "Approved checkout-only payment failover.",
         115, 450, ["src-backup-decision", "src-payment-incident"], "Devon Park"),
    node("billing-reconciliation", "Billing reconciliation", "service", "Settlement exports require the primary provider.",
         420, 460, ["src-billing-policy"], "Devon Park"),
    node("public-api", "Public API", "service", "Atlas integration API and event producer.",
         420, 30, ["src-api-contract"], "Alex Rivera"),
    node("identity-service", "Identity service", "service", "Token validation for API and checkout.",
         110, 30, ["src-auth-contract"], "Alex Rivera"),
    node("analytics-pipeline", "Analytics pipeline", "service", "Launch event ingestion and measurement.",
         730, 30, ["src-analytics-plan"], "Priya Shah"),
    node("launch-docs", "Launch docs", "service", "Customer-facing Atlas release documentation.",
         1050, 120, ["src-release-checklist"], "Mara Chen"),
    node("rollout-flags", "Rollout flags", "service", "Controlled Atlas release activation.",
         1050, 330, ["src-release-checklist"], "Mara Chen"),
    node("mara-chen", "Mara Chen", "person", "Product lead and Atlas launch owner.",
         1060, 550, ["src-team-roster"], status="active"),
    node("devon-park", "Devon Park", "person", "Payments and continuity owner.",
         110, 650, ["src-team-roster"], status="active"),
    node("alex-rivera", "Alex Rivera", "person", "API and identity owner.",
         110, -170, ["src-team-roster"], status="active"),
    node("priya-shah", "Priya Shah", "person", "Analytics and measurement owner.",
         740, -170, ["src-team-roster"], status="active"),
    node("platform-team", "Platform team", "team", "Payments, API and identity engineering.",
         -180, 650, ["src-team-roster"], status="active"),
    node("product-team", "Product team", "team", "Atlas launch coordination.",
         1060, 760, ["src-team-roster"], status="active"),
    node("data-team", "Data team", "team", "Launch measurement and reporting.",
         740, -360, ["src-team-roster"], status="active"),
    node("launch-brief", "Launch brief", "document", "Scope, date and launch dependency evidence.",
         760, 550, ["src-launch-brief"], "Mara Chen", "active"),
    node("payment-runbook", "Payment runbook", "document", "Controlled checkout failover procedure.",
         -180, 430, ["src-payment-runbook"], "Devon Park", "active"),
    node("release-checklist", "Release checklist", "document", "Cross-team owner sign-off requirements.",
         1340, 330, ["src-release-checklist"], "Mara Chen", "active"),
    node("api-contract", "API contract", "document", "Published integration and documentation contract.",
         1050, -80, ["src-api-contract"], "Alex Rivera", "active"),
    node("analytics-spec", "Measurement plan", "document", "Launch event and dashboard acceptance criteria.",
         440, -360, ["src-analytics-plan"], "Priya Shah", "active"),
    node("backup-decision", "ADR-017 fallback", "decision", "Approved checkout authorization fallback only.",
         -180, 240, ["src-backup-decision"], "Mara Chen", "active"),
    node("payment-incident", "INC-042", "incident", "Previous timeout: checkout recovered; billing waited.",
         420, 680, ["src-payment-incident"], "Devon Park", "resolved"),
]


def edge(source_id, target_id, relation, sources):
    return {"id": f"{source_id}--{relation.lower()}--{target_id}", "source": source_id,
            "target": target_id, "relation": relation, "label": relation.lower().replace("_", " "),
            "source_ids": sources}


EDGES = [
    edge("checkout", "payment-gateway", "DEPENDS_ON", ["src-payment-runbook"]),
    edge("atlas-launch", "checkout", "DEPENDS_ON", ["src-launch-brief"]),
    edge("billing-reconciliation", "payment-gateway", "DEPENDS_ON", ["src-billing-policy"]),
    edge("atlas-launch", "public-api", "DEPENDS_ON", ["src-launch-brief", "src-api-contract"]),
    edge("atlas-launch", "analytics-pipeline", "DEPENDS_ON", ["src-launch-brief", "src-analytics-plan"]),
    edge("atlas-launch", "launch-docs", "DEPENDS_ON", ["src-launch-brief"]),
    edge("atlas-launch", "rollout-flags", "DEPENDS_ON", ["src-release-checklist"]),
    edge("checkout", "identity-service", "DEPENDS_ON", ["src-auth-contract"]),
    edge("public-api", "identity-service", "DEPENDS_ON", ["src-auth-contract"]),
    edge("analytics-pipeline", "public-api", "DEPENDS_ON", ["src-analytics-plan"]),
    edge("launch-docs", "api-contract", "DEPENDS_ON", ["src-release-checklist"]),
    edge("backup-provider", "payment-gateway", "BACKUP_FOR", ["src-backup-decision", "src-payment-incident"]),
    edge("checkout", "backup-provider", "CAN_USE", ["src-payment-runbook", "src-backup-decision"]),
    edge("atlas-launch", "mara-chen", "OWNED_BY", ["src-team-roster"]),
    edge("payment-gateway", "devon-park", "OWNED_BY", ["src-team-roster"]),
    edge("checkout", "devon-park", "OWNED_BY", ["src-team-roster"]),
    edge("public-api", "alex-rivera", "OWNED_BY", ["src-team-roster"]),
    edge("analytics-pipeline", "priya-shah", "OWNED_BY", ["src-team-roster"]),
    edge("mara-chen", "product-team", "MEMBER_OF", ["src-team-roster"]),
    edge("devon-park", "platform-team", "MEMBER_OF", ["src-team-roster"]),
    edge("alex-rivera", "platform-team", "MEMBER_OF", ["src-team-roster"]),
    edge("priya-shah", "data-team", "MEMBER_OF", ["src-team-roster"]),
    edge("launch-brief", "atlas-launch", "DOCUMENTS", ["src-launch-brief"]),
    edge("payment-runbook", "checkout", "DOCUMENTS", ["src-payment-runbook"]),
    edge("release-checklist", "atlas-launch", "DOCUMENTS", ["src-release-checklist"]),
    edge("api-contract", "public-api", "DOCUMENTS", ["src-api-contract"]),
    edge("analytics-spec", "analytics-pipeline", "DOCUMENTS", ["src-analytics-plan"]),
    edge("backup-decision", "backup-provider", "APPROVES", ["src-backup-decision"]),
    edge("payment-incident", "payment-gateway", "AFFECTED", ["src-payment-incident"]),
    edge("payment-incident", "checkout", "AFFECTED", ["src-payment-incident"]),
    edge("payment-incident", "backup-provider", "RESOLVED_WITH", ["src-payment-incident"]),
    edge("payment-incident", "billing-reconciliation", "AFFECTED", ["src-payment-incident"]),
    edge("backup-provider", "devon-park", "OWNED_BY", ["src-team-roster"]),
    edge("billing-reconciliation", "devon-park", "OWNED_BY", ["src-team-roster"]),
]
