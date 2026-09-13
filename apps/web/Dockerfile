FROM node:22.22.1-slim AS builder

WORKDIR /workspace
RUN npm install --global pnpm@12.4.1

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile --filter @agent-hub/web...

COPY apps/web apps/web
RUN pnpm --filter @agent-hub/web build

FROM node:22.22.1-slim AS runner

ENV NODE_ENV=production
WORKDIR /workspace

COPY --from=builder /workspace/apps/web/.next/standalone ./
COPY --from=builder /workspace/apps/web/.next/static ./apps/web/.next/static

EXPOSE 3000
CMD ["node", "apps/web/server.js"]
