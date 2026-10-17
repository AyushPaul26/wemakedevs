# Relay test deployment

The user wants a real browser testing link and has authorized deployment. Use one free Render Docker web service: the built React frontend and FastAPI share its HTTP port, with the pinned FalkorDB running on container loopback. This is a single-workspace test deployment. Free Render storage is temporary; a replacement container reseeds the sample company and loses added notes, investigations, and tasks.

Deployment decisions: require a password for the UI and API, keep only the real health check public, exclude local credentials and development data from the Docker build, and keep the current local development workflow running. Render generates the preview password. The Groq key must be supplied privately to the hosting environment. No paid service is selected.

- [x] Inspect current hosting identities and network rules: none are configured.
- [x] Save the missing Render API credential requirement and destination in the cloud draft.
- [x] Add and verify a deployment-only authentication/static-serving boundary.
- [x] Build the Docker image with frozen dependencies and test its real graph, frontend, auth, and Ripple under a 512 MiB limit.
- [x] Add a free Render Blueprint and concise deployment instructions.
- [ ] Check source for secrets, commit the deployment-ready app to the existing branch, and push using the existing GitHub authentication.
- [ ] Create the public service and verify its HTTPS URL when hosting access is supplied. If access remains absent, provide the concrete deployment link and exact remaining account action; do not claim it is an app URL.

Review focus: missing password must fail closed; health must fail when the graph is unavailable; unknown API paths must not return frontend HTML; Redis must never bind publicly; local `.env`, data, and model credentials must not enter Git or image layers.
