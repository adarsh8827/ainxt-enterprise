# Build context is the REPOSITORY ROOT, not ai-ui/.
#
# ai-ui cannot be built in isolation: vite.config.js aliases '@abs' to
# ../AgentStudio/frontend/src AND '@ecosystem-ui' to ../packages/ecosystem-ui/src,
# so both sibling source trees must be present or the build fails with
#   [vite:load-fallback] Could not load /AgentStudio/frontend/src/BuildStudio.jsx
# or
#   [vite:load-fallback] Could not load /packages/ecosystem-ui/src/index
#
#   docker build -f ai-ui/Dockerfile .

# ── Build stage ────────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app/ai-ui

# Dependencies first so a source-only change does not re-resolve the tree.
COPY ai-ui/package.json ./
COPY ai-ui/package-lock.json* ./
# `npm ci` when a lockfile is present, `npm install` otherwise. ai-ui ships no
# lockfile today, so this stays correct either way.
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; \
    else npm install --no-audit --no-fund; fi

# Sibling sources reached through the '@abs' alias.
COPY AgentStudio/frontend/src /app/AgentStudio/frontend/src
# Sibling sources reached through the '@ecosystem-ui' alias (task F-2) --
# same reason as the @abs copy above; missing until now, so a real
# container build of ai-ui always failed outright.
COPY packages/ecosystem-ui/src /app/packages/ecosystem-ui/src

COPY ai-ui/ ./

# Vite inlines VITE_* vars at build time from the process environment or an
# ai-ui/.env file — compose's `environment:`/root .env never reach this
# build stage on their own, so each one needed here must be declared as a
# build ARG and re-exported as ENV before `npm run build` runs.
ARG VITE_ECOSYSTEM_CHAT_SKILLS=false
ENV VITE_ECOSYSTEM_CHAT_SKILLS=$VITE_ECOSYSTEM_CHAT_SKILLS

RUN npm run build

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# vite builds with base '/portal/', so the bundle is served from that prefix.
COPY --from=builder /app/ai-ui/dist /usr/share/nginx/html/portal
COPY ai-ui/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 5173
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:5173/portal/ >/dev/null 2>&1 || exit 1
