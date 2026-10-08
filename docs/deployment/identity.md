# Platform identity contract

Agent Hub does not implement sign-in. Production consumes one authenticated subject supplied by the hosting platform. The platform owns its Nginx configuration and sign-in behavior; this document records the identity value Agent Hub expects.

## Production requirements

1. The API container is private to the deployment network and cannot be reached directly by a browser.
2. The platform supplies a stable authenticated subject in `X-Agent-Hub-Subject`. That value must not be chosen by the browser.
3. Next.js forwards only the configured identity header and required content headers to the API; it does not forward arbitrary browser headers.
4. The API runs with `AGENT_HUB_ENVIRONMENT=production` and `AGENT_HUB_IDENTITY_MODE=trusted_header`. Startup configuration rejects a production fixed identity.
5. A missing or blank trusted subject is rejected before Project data is read.

The existing `deploy/nginx/agent-hub.conf.template` is an illustrative platform example, not an Agent Hub deployment or acceptance task.

## Development

Development defaults to `AGENT_HUB_IDENTITY_MODE=fixed` and `AGENT_HUB_FIXED_IDENTITY_SUBJECT=local-user`. The fixed adapter ignores identity headers completely, so a browser cannot choose another subject by forging a header. Isolation tests construct separate fixed adapters for separate subjects.

The fixed adapter is development and test infrastructure, not a fallback when production authentication is unavailable.
