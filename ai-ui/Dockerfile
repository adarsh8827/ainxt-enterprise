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

# Vite inlines import.meta.env.VITE_* at build time, never at container
# runtime -- unlike a native `npm run dev` (which reads the repo-root .env
# directly, per vite.config.js's own envDir), a Docker build has no .env
# file in its context at all, so these must arrive as explicit build args
# from docker-compose.yml's ai-ui.build.args. Without this, VITE_* reads
# (e.g. useEcosystemChatSkills.js's VITE_ECOSYSTEM_CHAT_SKILLS gating the
# chat "+" skills menu, AgentStudio's CatalogPicker.jsx VITE_ECOSYSTEM_
# AGENTSTUDIO_SKILLS) always resolve undefined in the built bundle,
# regardless of what the root .env sets -- a real gap found live.
ARG VITE_ECOSYSTEM_CHAT_SKILLS=true
ARG VITE_ECOSYSTEM_AGENTSTUDIO_SKILLS=false
ENV VITE_ECOSYSTEM_CHAT_SKILLS=$VITE_ECOSYSTEM_CHAT_SKILLS
ENV VITE_ECOSYSTEM_AGENTSTUDIO_SKILLS=$VITE_ECOSYSTEM_AGENTSTUDIO_SKILLS

RUN npm run build

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# vite builds with base '/portal/', so the bundle is served from that prefix.
COPY --from=builder /app/ai-ui/dist /usr/share/nginx/html/portal
COPY ai-ui/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 5173
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:5173/portal/ >/dev/null 2>&1 || exit 1
