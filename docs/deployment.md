# Test Relay on Render

The repository includes a single-container Render Blueprint on the `work`
branch. It serves the built frontend and API together, with the pinned FalkorDB
bound only to container loopback. `render.yaml` selects the free plan and
disables automatic deployments.

The existing free Render app remains on the earlier `c40a08f` baseline, verified
live by the user. This workflow release has **not** been deployed there. The
instructions below describe the new release after a deliberate manual
deployment; they do not change the running service or its existing login flow.

1. Open [Deploy Relay on Render](https://dashboard.render.com/blueprint/new?repo=https%3A%2F%2Fgithub.com%2FAyushPaul26%2Fwemakedevs), connect the repository if prompted, select branch `work`, and confirm the free service plan. For an existing service, review and deploy the intended commit manually rather than creating a duplicate service.
2. Wait for the web service to become healthy. Render supplies its actual `https://…onrender.com` app URL; the Blueprint setup link is not the running app.
3. Set `RELAY_PUBLIC_ORIGIN` to the actual HTTPS app origin (for this service, `https://relay-company-brain.onrender.com`). The first administrator is `owner`, using the securely configured `RELAY_ACCESS_PASSWORD`. The free demo Blueprint also opts into separate `demo-operator` and `demo-auditor` accounts with different generated passwords. Retrieve these only from Render's private environment settings; never put them in Git, chat, or a recording.
4. For live answers, add `RELAY_MODEL_API_KEY` securely in Render's environment settings and manually redeploy. The configured provider is Groq. Without a key, the app identifies Guided demo mode. A blocked or failed live call remains a failure; it does not become a successful live response. Never put credentials in Git or a frontend variable.

The new release uses authenticated member sessions and CSRF checks for mutations.
The sign-in page and its static assets are public, as is `/api/health` for hosting
checks. Protected API data requires a valid member session and server-side
resource authorization. Login assets being public does not expose uploaded
files, Finance evidence or completed reports.

`RELAY_ACCESS_PASSWORD` is a first-account bootstrap input, not a shared password
that grants every member access or resets an existing account. The supplied
container wrapper nevertheless requires this variable to remain configured with
at least 16 characters on every boot, including restarts with existing accounts.
Changing it does not change stored member passwords. The API's bootstrap behavior
and the container's configuration requirement are separate.

The free service has **temporary storage**. It can sleep, take time to wake, and
lose newly added notes, memory, uploads, approvals and tasks when replaced or
redeployed. An entirely fresh ephemeral workspace installs the fictional fixture
once. Startup never clears or reseeds an existing graph to repair it. This
Blueprint is not evidence that workflow data will survive a hosted replacement.

## Free-tier workflow startup

The container prepares storage before starting the API. `RELAY_ENABLE_EXECUTION=1`
explicitly enables its background executor after readiness succeeds. Omitting
the flag leaves the stored setting unchanged; a fresh workspace starts disabled.
This flag does not approve Finance work or waive any workflow permission checks.

`RELAY_PROVISION_DEMO_ACCOUNTS=1` opts into offline account setup without requiring
a paid shell. It requires distinct, private passwords of at least 16 characters
in `RELAY_ACCESS_PASSWORD`, `RELAY_OPERATOR_PASSWORD`, and
`RELAY_FINANCE_AUDITOR_PASSWORD`. The optional login settings are
`RELAY_OPERATOR_LOGIN` (default `demo-operator`) and
`RELAY_FINANCE_AUDITOR_LOGIN` (default `demo-auditor`). The setup creates the owner
first if no accounts exist, then the operator and Finance auditor, and assigns
that auditor to the Finance approval policy. No account password is hardcoded.

A completed setup is recorded in the graph. Repeated startup preserves account
passwords, disabled accounts and subsequent reviewer assignments. Changing an
environment password does not reset a stored account. Conflicting existing
logins, an existing assigned reviewer, or incomplete provisioning stops startup
for inspection instead of silently replacing permissions. The default is off;
the free demo Blueprint deliberately opts in. The runtime image also includes
`scripts/manage_members.py` for trusted operators with shell access.

For the existing Blueprint-managed service, add the new settings through Render
or deliberately sync the reviewed Blueprint before manually deploying the
intended commit. Pushing Git code alone does not update service variables.
Keep the existing Groq configuration and service identity; do not create a
duplicate service or upgrade its plan for this demo.

## Durable deployment preparation

[The separate persistent Blueprint](../deploy/render-persistent.yaml) prepares a
single paid Starter instance and a 10 GB disk at `/app/.data`. It is a review
artifact, not an update to the active free service. No paid service or disk has
been activated. Obtain the current account-specific service/disk quote and the
owner's approval before importing or syncing it.

See [durable storage and recovery](persistence.md) for the configurable
`RELAY_DATA_DIR`, non-root volume ownership, explicit first installation,
backup-gated offline migration, executor opt-in, consistent backups and explicit
restore. Persistent startup refuses a missing or mismatched storage marker;
`RELAY_INITIALIZE_DATA=1` is a deliberate first-install setting for an empty disk,
not a repair for lost data. Activating this separate paid Blueprint is not part
of the authorized free-tier deployment.

## HTTPS sign-in behind the hosting proxy

Set `RELAY_PUBLIC_ORIGIN` to the exact HTTPS origin used in the browser. The
hosted sign-in endpoint compares an explicit browser `Origin` with this configured
value, so internal HTTP between Render's proxy and the container does not cause
a valid HTTPS login to fail. The configured origin must not contain credentials,
a path, query, fragment, or wildcard. An unrelated browser origin is rejected.

Without a configured public origin, the original same-request-origin comparison
remains. Proxy-forwarded scheme/client headers are a separate setting:
`FORWARDED_ALLOW_IPS` must contain verified proxy IPs/CIDRs if used. The public
origin setting does not trust arbitrary forwarded headers, change CORS, or
weaken session CSRF checks. No wildcard proxy trust is needed for this login fix.

Before claiming a newly deployed release is ready, verify sign-in from its real
HTTPS page through the provider ingress: the public host and forwarded HTTPS
scheme must match the browser origin, sign-in must succeed, and the session
cookie must retain `Secure` and `HttpOnly`. An unrelated origin must still be
rejected. Then sign in as the separate auditor and verify an actual protected
workflow, not just the public health endpoint.

## Automated deployment from Codex

Render API operations require an authorized `RENDER_API_KEY`, supplied through
secure environment settings for `api.render.com`, plus repository access in
Render. Existing service identity, target commit, storage and deployment intent
must be checked before changing that service. Saving a credential requirement or
configuration draft does not supply the secret, grant access, publish an
environment or deploy this release. No Render API deployment was performed as
part of the current local verification.

## Container validation

Build using `docker build -t relay-preview .`. In this managed cloud environment,
use the provided proxy and CA bundle while retaining TLS verification:

```sh
BUILDX_CONFIG=/workspace/.cache/docker-buildx docker build \
  --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt \
  -t relay-preview .
```

Supply `RELAY_ACCESS_PASSWORD` through a private environment file or platform
settings, with at least 16 characters. Expose only port 10000 and use HTTPS at
the hosting boundary. Redis listens only on container loopback. The build context
excludes local credentials, development data, Git metadata and dependency caches.

The current release passed a real 512 MiB container replacement test against the
same private named volume: a waiting approval, 12 source versions, two
authenticated downloads, case history and SQLite checkpoints survived, and no
completed effect repeated. This establishes local Docker behavior; hosted disk
permissions, current pricing and the deployed release still require separate
verification. See [the verification record](verification.md) for the exact image
and current test status.

The free Blueprint fields were originally checked against Render's
[official Docker example](https://github.com/render-oss/skills/blob/main/skills/render-deploy/assets/docker.yaml)
and deployment references. A local build/test does not establish Render quota or
change the running free baseline.
