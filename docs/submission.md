# Relay: Graph Hacks submission

## Entry details

| Field | Value |
| --- | --- |
| Project | Relay |
| Tagline | A company brain that connects evidence, remembers work, and executes tasks with scoped human approval. |
| Source code | https://github.com/AyushPaul26/wemakedevs/tree/work |
| Live application | https://relay-company-brain.onrender.com |
| Demo video | [Watch the full walkthrough on YouTube](https://www.youtube.com/watch?v=bvLC4aGHssA) |
| Lead track | Company Brain |
| Additional tracks | Agents That Act on Connected Data; Agent Memory and Coordination |
| Setup and graph model | [README](../README.md) |
| Actual Cypher and graph algorithms | [README query guide](../README.md#cypher-and-graph-algorithms), [company graph queries](../backend/relay/graph_store.py), and [workflow queries](../backend/relay/workflow_store.py) |
| Implementation and verification | [Verification record](verification.md), [workflow walkthrough](workflow-demo.md) |
| AI-assistance disclosure | [README disclosure](../README.md#ai-assistance-and-participant-contribution) |

## Project description

Relay helps a team connect company knowledge to the work that follows. In the fictional Meridian workspace, people can find owners and original evidence, ask company questions, and use Ripple to explore how a disruption travels through recorded dependencies. Investigations are saved so users can revisit their findings.

The invoice-review workflow connects that knowledge to execution. Company research can continue while protected Finance processing waits for a separate auditor. The auditor reviews the exact document versions, permitted tools, and output audience. Approved tools compare invoice and purchase-order rows, produce HTML and CSV reports, and create an internal exception case with execution receipts. Optional output-review gates let the requester decide how much additional human review is needed.

When evidence changes, Relay preserves the previous version, marks affected work stale, requires fresh approval, and reuses unchanged work. A corrected invoice can resolve the existing case instead of creating disconnected history. FalkorDB supplies the relationships, permissions, workflow state, and memory behind these operations; LangGraph coordinates the stages.

## Track descriptions

**Company Brain:** Relay connects company ownership, dependencies, source evidence, decisions, and investigations. Users can inspect supporting documents and explore hypothetical dependency changes without rewriting company facts.

**Agents That Act on Connected Data:** Graph queries determine dependency impact and whether workflow steps are eligible to run. Scoped approval enables tools that compare documents, generate reports, update an internal case, and record the work performed.

**Agent Memory and Coordination:** Researcher, Planner, and Archivist stages retrieve, compose, and save investigations. Workflow branches share persisted graph state, wait at approval boundaries, retain receipts, and reuse unchanged completed work when a plan is revised. These are coordinated workflow stages, not a claim of three independent language models.

## Demo video

[Watch the full demo video on YouTube](https://www.youtube.com/watch?v=bvLC4aGHssA).

The reviewed full walkthrough is `Relay_full_walkthrough_minimal_edit (1).mp4`, with a duration of **16:27**. Use the linked video in the submission form. Check that judges can view the link without requesting access and that the submission form has no additional duration restriction.

Approximate chapters in that version:

| Time | Demonstration |
| --- | --- |
| 00:00 | Company graph, ownership, and original evidence. |
| 00:28 | FalkorDB's role in the architecture. |
| 01:17 | Ripple: dependency exposure and a documented backup assumption. |
| 02:16 | Company question, evidence, and agent handoffs. |
| 03:12 | Saved investigation memory, followed by adding company knowledge. |
| 04:10 | Uploading a document, confirming company links, and asking about an exact attachment. |
| 05:47 | Finance uploads and invoice-review setup. |
| 06:55 | Parallel work and the separate Finance auditor's scope and decision. |
| 08:13 | Report and case proposals with separate output approvals. |
| 09:12 | Execution receipts, decision history, downloads, and the internal case. |
| 10:16 | Opened discrepancy CSV. |
| 10:45 | Workflow follow-up question and saved investigation. |
| 11:39 | Corrected invoice, preserved versions, and revised plan. |
| 12:41 | Fresh Finance approval for changed evidence. |
| 13:08 | Reused work and the existing case resolving with no discrepancy. |
| 14:06 | Change requests, cancellation, rejection, search, drafts, and sign-out. |

The [verification record](verification.md#limits) describes the release's scope and limitations; the recording is a product demonstration rather than a replacement for those checks.

## Judging access

The hosted workspace requires sign-in. The main demonstration uses `demo-operator`; the Finance decision uses the separate `demo-auditor` account. Supply the corresponding demo credentials through a private judging-access field or the organizer's approved private channel. Do not publish credentials in this repository or in the video. Use separate browser profiles for the two accounts so their sessions do not replace each other.

The free Render service may sleep and uses temporary storage. Follow [the local setup](../README.md#run-locally) if the hosted instance is unavailable; [member provisioning](persistence.md#provision-members-and-the-finance-reviewer) explains how to create independent requester and auditor accounts. Local Guided demo mode needs no model API key and still uses real FalkorDB queries, approval checks, invoice calculations, reports, and memory.

## Data, reuse, and AI assistance

The checked-in Meridian company data and invoice examples are fictional. Use only permitted public, synthetic, or owned data in any additional demonstration. Finance classification controls access inside the example workspace; it does not turn the fictional dataset into real private company information.

Dependencies and reuse boundaries are documented in [third-party notices](../THIRD_PARTY_NOTICES.md) and [the reuse assessment](relay-reuse-plan.md). The [AI-assistance disclosure](../README.md#ai-assistance-and-participant-contribution) identifies how Codex and ChatGPT helped create the submission and the human direction involved.

## Final submission steps

1. Copy the demo video, repository, and live-app links from the entry details above into the submission form.
2. Select Company Brain, Agents That Act on Connected Data, and Agent Memory and Coordination in the submission form, consistent with this entry.
3. Provide private demo access or point judges to the complete local setup.
4. Include the AI-assistance disclosure wherever the form requests it.
5. Confirm the actual team members, permitted data, original-work timing, and ability to explain the implementation. Repository documentation cannot make these personal confirmations on the participant's behalf.
6. Submit before **October 18, 2026, 11:59 PM IST**, following the supplied Graph Hacks rules and any later organizer updates.

This document prepares the entry; it does not assert that the submission form has already been filed.
