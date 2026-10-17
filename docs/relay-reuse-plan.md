# Relay: repository and skill shortlist

Research date: 17 October 2026. This is a reuse assessment, not an implemented or runtime-tested application.

## Product direction

Relay is a company assistant that connects people, projects, documents, decisions, and tasks. Its signature feature, Ripple, explores a hypothetical change and shows the affected dependencies with supporting sources. Agents investigate, prepare a response, retain useful memory, and create follow-up tasks after approval.

## Confirmed hackathon requirements

Source: the Graph Hacks screenshots supplied by the user in this conversation.

- FalkorDB must be the primary graph database and support a central part of the product.
- General libraries, templates, and infrastructure may be reused. The submission and its main FalkorDB implementation must be new work completed during the event.
- Any programming language, framework, frontend, or deployment platform is allowed.
- A project can enter one, two, or all three tracks. Each has its own prize.
- A live deployment is preferred. Without one, the submission needs complete local setup instructions and a working demo video.

Recommended main pitch: **Track 3, Company Brain**. Demonstrate Track 1 through graph-driven investigation and approved task creation, and Track 2 through persistent memory and visible agent handoffs. Multiple-track entry remains available under the supplied rules.

## Recommended building blocks

| Repository | Role | Selection |
| --- | --- | --- |
| [FalkorDB/FalkorDB](https://github.com/FalkorDB/FalkorDB) | Primary store for company facts, relationships, source references, and agent memory. Executes the live graph queries that drive Ripple. | Required. Core database is SSPLv1; do not describe every dependency as MIT. |
| [FalkorDB/falkordb-py](https://github.com/FalkorDB/falkordb-py) | Official Python client for direct, parameterized Cypher queries and controlled graph writes. | Core. MIT, Python 3.10+. No model credential needed for database operations. |
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | Researcher-to-planner workflow, durable execution checkpoints, and approval/resume handling. | Core for the multi-agent workflow. MIT, Python 3.10+. Use a file-backed SQLite checkpointer for the first deployment; company knowledge and long-term memory remain in FalkorDB. |
| [xyflow/xyflow](https://github.com/xyflow/xyflow) | React Flow's interactive nodes and edges for the company map and highlighted Ripple paths. | Core UI library. MIT. Install the published `@xyflow/react` package rather than cloning the entire monorepo. It renders graph results; it is not a graph database or simulation engine. |
| [assistant-ui/assistant-ui](https://github.com/assistant-ui/assistant-ui) | Reusable chat, streamed messages, tool-result cards, and approval UI. | Preferred UI accelerator, subject to a small backend-adapter compatibility check. MIT. Use primitives/custom runtime with our backend; managed thread storage is optional. |
| [FalkorDB/GraphRAG-SDK](https://github.com/FalkorDB/GraphRAG-SDK) | Document ingestion, typed extraction, evidence chunks, and grounded retrieval against FalkorDB. | Preferred ingestion accelerator behind an adapter. Apache-2.0, Python 3.10+. Requires configured LLM and embedding models; its native/ML dependencies need an installation check before making it critical to the demo. |
| [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) | Map source code and selected project documents; import useful graph fragments with provenance. | Retain the already cloned repository. Apache-2.0 with retained MIT notices for older contributions. Optional ingestion/development aid; Relay must still read/write its live primary graph in FalkorDB. |

Use a small Python API and React/TypeScript interface around these packages. Each component should have one owner and one job; adding another framework requires a concrete capability the selected stack lacks.

Integration details to preserve: GraphRAG-SDK's maintained ontology example uses `Ontology`, `Entity`, `Relation`, and `Attribute`; older `GraphSchema` aliases in its README are deprecated. assistant-ui's LangGraph example expects LangGraph deployment/thread APIs, so it does not directly connect to an arbitrary FastAPI route wrapping a Python graph. Use its custom-runtime boundary for our API instead of assuming that adapter is plug-and-play.

LangGraph restarts an interrupted node on approval resume. Keep task execution after approval and give writes idempotency keys. Use a persistent checkpoint file, stable session/thread IDs, and explicit approval ownership; checkpoints alone do not guarantee exactly-once actions or authorization.

## Alternatives reviewed

- **[getzep/graphiti](https://github.com/getzep/graphiti)**: Apache-2.0, Python 3.10+. Strong candidate for temporal facts and evolving agent knowledge; has a real FalkorDB driver. Defer it for the first version because it overlaps document extraction and graph-memory responsibilities. Revisit if temporal fact reconciliation becomes central. Current Kuzu support is explicitly deprecated, so it is not a recommended database route. FalkorDB Lite support requires Python 3.12+.
- **[CopilotKit/CopilotKit](https://github.com/CopilotKit/CopilotKit)**: MIT. Useful agent/UI integration, but do not add it alongside assistant-ui by default. Choose a single UI/runtime integration after a compatibility probe.
- **[fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template)**: MIT. Useful reference for React, Python API, tests, and deployment. Its PostgreSQL, account/email, and deployment infrastructure are additional commitments; avoid adopting the full template merely to obtain a starter screen.

## Relay's original implementation

1. **Company graph model:** typed people, teams, projects, services, documents, decisions, and dependencies; source references and freshness attached to facts.
2. **Ripple:** directed dependency queries and explicit propagation rules. A connected path alone is not proof of causal impact. Clearly distinguish observed facts, scenario assumptions, and possible consequences.
3. **Persistent agent memory:** investigations, source-linked findings, outcomes, and handoff ownership stored in FalkorDB. LangGraph checkpoints separately retain execution position and approval state.
4. **Action workflow:** proposed tasks with owners and supporting evidence, explicit user approval, and idempotent creation. A completed proposal is not evidence that a real-world blocker has been resolved.
5. **Product experience:** linked answers, interactive company map, scenario comparison, visible handoffs, memory history, and an action board.

Document facts, memory retrieval, and scenario traversal must execute against FalkorDB during the demo. A JSON export, decorative database connection, or React Flow visualization alone would not satisfy the central-database requirement.

Use application-owned parameterized queries for Ripple and writes. Do not execute arbitrary model-generated Cypher as an action. Keep the hypothetical scenario separate from authoritative company facts.

## Skills already available in this session

| Skill | Purpose |
| --- | --- |
| `superpowers:brainstorming` | Settle the product's purpose, scope, and demonstration before coding. |
| `superpowers:writing-plans` | Turn the reviewed design into implementation steps when that stage is reached. |
| `frontend-design-premium:frontend-design` + `frontend-design-premium:frontend-design-premium` | Design the map/chat workspace and maintain shared visual and interaction behavior. |
| `superpowers:test-driven-development` | Verify business logic such as dependency direction, scenario isolation, memory persistence, and action deduplication. |
| `superpowers:systematic-debugging` | Diagnose setup or application failures when they occur. |
| `superpowers:verification-before-completion` | Run the actual application, tests, build, and representative workflow before claiming completion. |

No additional plugin installation is required for this shortlist. Skills guide the development process; the repositories provide reusable code.

## Readiness and remaining checks

This research inspected official repository sources, manifests, licenses, examples, and remote HEADs. It did not install these packages or prove their combined runtime compatibility. Only Graphify is cloned; the other projects should normally be consumed as dependencies or narrowly selected examples.

Before committing to package versions, exercise the FalkorDB client, one ingestion sample, LangGraph's file-backed checkpoint/approval flow, and the selected chat adapter. Confirm model/embedding access through existing environment bindings before requesting any missing credentials. Do not put credentials in project files or chat.

The implementation's acceptance checks should cover a real FalkorDB query, correct dependency direction, source-linked answers, persistence across service restarts, isolated hypothetical scenarios, approved and deduplicated task creation, and the browser interaction at desktop and narrow widths. These are planned checks, not reported results.

## Reviewed source revisions

These are research snapshots, not an installation lockfile. Pin compatible released package versions after runtime validation.

| Repository | Reviewed commit |
| --- | --- |
| FalkorDB/FalkorDB | `0f45a8685aa8d542f026b4f5f6bcaa0fbb43c1c9` |
| FalkorDB/falkordb-py | `31f63f44a5745b9bec65969a1db706906718cb82` |
| FalkorDB/GraphRAG-SDK | `35e67a0b27fdcc7f2c28508b09e86169851a8187` |
| Graphify-Labs/graphify | `86c57be8204673c2a1b9849a3292a7dd3ab373d8` |
| getzep/graphiti | `d50741d1bf463cbe3859eb73914cbff1b66839e6` |
| langchain-ai/langgraph | `41c9c22fdc83d68a2859d0c9a2b627c8615a792f` |
| xyflow/xyflow | `654ba5a5e04f3404bc4db2eee88bfa15866d203d` |
| assistant-ui/assistant-ui | `69668210c9476323380067307284509f707b507a` |
| CopilotKit/CopilotKit | `7b446f86e823e8af4695e78f7a61e800844a9373` |
| fastapi/full-stack-fastapi-template | `b1125d8839482cb7bbae603ddc6d0081bf87532e` |

Primary evidence includes each pinned README and license, GraphRAG-SDK's `graphrag_sdk/pyproject.toml` and ontology examples, LangGraph's checkpoint packages, React Flow's `packages/react/package.json`, and the locally reviewed Graphify architecture and public APIs.
