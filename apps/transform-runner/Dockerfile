FROM denoland/deno:2.9.7@sha256:fa335acdf6b72106eda2cb6a8cb5f4187e7630e357467489db4b2e7352d5e432 AS runtime

ENV DENO_DIR=/deno-dir
WORKDIR /app
COPY apps/transform-runner/deno.lock apps/transform-runner/worker.mjs ./
RUN deno cache --frozen-lockfile worker.mjs
COPY apps/transform-runner/runner.mjs apps/transform-runner/server.mjs ./

FROM runtime AS test
COPY apps/transform-runner/runner.test.mjs ./
RUN deno test --no-check -A runner.test.mjs

FROM runtime AS production
USER 65534:65534
EXPOSE 8000
CMD ["run", "--cached-only", "--no-prompt", "--allow-read=/app,/deno-dir", "--allow-net=0.0.0.0:8000", "--allow-run=/usr/bin/deno", "server.mjs"]
