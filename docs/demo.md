# Relay demo walkthrough

Relay connects a company's people, services, decisions, and past incidents. **Ripple** shows which work is exposed to a hypothetical service outage, then compares a documented recovery assumption. Use fictional Meridian data throughout the demo.

## Two-minute story

1. Start Relay using the README. Point out the **Sample workspace** and **Guided demo** labels. With no model credential, answers are deterministic compositions of stored evidence; the database, workflow, and memory are real.
2. Open the launch map. Select **Payment gateway** and inspect its owner and source evidence.
3. Run Ripple for the payment gateway. Show three exposed dependencies: Checkout, Atlas launch, and Billing reconciliation. Follow the payment → checkout → launch path. These are dependency counts, not predictions of outage probability.
4. Enable the backup-provider assumption. Exposure drops from three to one: billing still depends on the primary provider's settlement export. Open the cited runbook and previous incident. The simulation has not changed authoritative company facts.
5. Ask **“What happens to the Atlas launch if payments fail?”** Read the answer and open a citation. Expand the Researcher → Planner → Archivist steps.
6. Open **Actions**. Approve one proposed task, then mark it complete. Approval only changes an internal Relay task; no external ticket, message, or failover occurs.
7. Open **Memory**, then reload. The investigation remains available from FalkorDB. Restarting the API preserves it too. LangGraph stores session checkpoints separately in SQLite.
8. In **Knowledge**, add a short document note and open it again. This stores a searchable source; it does not claim automatic entity extraction.

## Optional live Groq mode

Put a valid Groq credential in the secure `RELAY_MODEL_API_KEY` environment setting and restart the API. The UI reports live mode when a credential is configured. Ask the same question; the service sends bounded graph evidence to Groq and validates returned citation IDs and task owners. A provider rejection or timeout produces an error, never a fake successful live answer.

ChatGPT Pro covers use of ChatGPT and eligible Codex features. It does not supply API credits to this application's backend. Relay's Groq usage is subject to the separate Groq account's model availability, rate limits, and billing settings.

## Submission recommendation

Lead with **Track 3 — Company Brain**: connected company facts, ownership, source-backed investigation, and traceable decisions are the product's central experience.

| Track | Implemented proof |
| --- | --- |
| 1: Agents acting on connected data | Real directed FalkorDB traversal, Ripple scenarios, source-linked task proposals, human approval |
| 2: Agent memory and coordination | Researcher/Planner/Archivist LangGraph workflow, persistent session checkpoints, investigations and task state stored in FalkorDB |
| 3: Company Brain | People, teams, services, launch, documents, decisions, and incident history connected in one graph |

The supplied rules allow submitting to all three. Describe each demonstrated behavior honestly; persistence and workflow handoffs do not establish production multi-tenant isolation or high-concurrency scale.

## Record the walkthrough

With the development servers running, system Chromium and ffmpeg installed:

```sh
node scripts/record-demo.mjs
```

This captures real app interactions into a silent `.data/relay-demo.mp4`: company map, outage exposure, backup comparison, original evidence, investigation handoffs, task approval, and persistent memory. It uses the current provider mode; keep Guided demo visibly identified when no live model is configured. Add narration using the story above for a final submission.

## Reuse and limits

The application and its central FalkorDB behavior are new work. Open-source libraries provide the database, workflow engine, graph renderer, and assistant UI. Graphify exports can be imported using the adapter documented in `graphify.md`. GraphRAG-SDK is an optional dependency for future extraction, not a completed ingestion integration.

This is a single sample-workspace development application. It has no production authentication, public deployment, live business connectors, or automatic external actions. A submission should include a recorded walkthrough of the working app, these setup instructions, and the exact verified revision.
