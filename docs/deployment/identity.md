# Platform identity contract

Agent Hub does not implement sign-in. Production consumes one subject asserted by the platform Nginx ingress.

## Production requirements

1. The API container is private to the deployment network and cannot be reached directly by a browser.
2. The platform authentication layer derives a stable subject from its authenticated session.
3. Nginx overwrites `X-Agent-Hub-Subject` with that subject. It must not append to or preserve a client-supplied value.
4. Next.js forwards only the configured identity header and required content headers to the API; it does not forward arbitrary browser headers.
5. The API runs with `AGENT_HUB_ENVIRONMENT=production` and `AGENT_HUB_IDENTITY_MODE=trusted_header`. Startup configuration rejects a production fixed identity.
6. A missing or blank trusted subject is rejected before Project data is read.

`deploy/nginx/agent-hub.conf.template` shows the required overwrite. The hosting platform must bind `$agent_hub_authenticated_subject` to its own authentication result before using the template.

## Development

Development defaults to `AGENT_HUB_IDENTITY_MODE=fixed` and `AGENT_HUB_FIXED_IDENTITY_SUBJECT=local-user`. The fixed adapter ignores identity headers completely, so a browser cannot choose another subject by forging a header. Isolation tests construct separate fixed adapters for separate subjects.

The fixed adapter is development and test infrastructure, not a fallback when production authentication is unavailable.
