# apps/web/Dockerfile
#
# Multi-stage build:
#   Stage 1 (builder): Node 20 Alpine – install deps and build Vite SPA.
#   Stage 2 (final):   Nginx Alpine    – serve the static dist/ output.
#
# API routing: in development Vite's dev-server proxies /api/* to the FastAPI
# backend and strips the /api prefix (see vite.config.ts).  In production the
# nginx config replicates that behaviour with a location /api/ proxy_pass block
# so the built bundle (which defaults API_BASE to '/api') can still reach the
# api service without any VITE_API_BASE build-time override.
#
# SPA routing: try_files falls back to index.html for unknown paths so that
# React Router can handle client-side routes like /items/:slug.
#
# Build context: repo root (docker-compose sets context: .)

# ─── Stage 1: Builder ────────────────────────────────────────────────────────
FROM node:26-alpine AS builder

WORKDIR /app

# Copy package manifests first for layer-cache efficiency
COPY apps/web/package.json apps/web/package-lock.json* /app/

# Reproducible install from the committed lockfile. Fail loud if it is missing
# rather than silently regenerating an unpinned tree.
RUN npm ci

# Copy the rest of the web source
COPY apps/web /app/

# Web auth config is baked into the bundle at build time (Vite env), which
# makes images per-environment; defaults keep the dev header seam. Override
# via compose build.args (sourced from .env) for password-mode deployments.
ARG VITE_AUTH_MODE=dev
ARG VITE_IDENTITY_CLAIM=
ENV VITE_AUTH_MODE=$VITE_AUTH_MODE \
    VITE_IDENTITY_CLAIM=$VITE_IDENTITY_CLAIM

# Build the production bundle
RUN npm run build

# ─── Stage 2: Final (serve) ──────────────────────────────────────────────────
FROM nginx:alpine

# Write a minimal nginx config that:
#   - Proxies /api/* → http://api:8000/* (strips the /api prefix to match the
#     Vite dev-server rewrite: path.replace(/^\/api/, ''))
#   - Serves static files from /usr/share/nginx/html
#   - Falls back to index.html for unknown paths (SPA client-side routing)
#
# Note: the trailing slash on proxy_pass strips the /api prefix before
# forwarding, matching the Vite rewrite rule in vite.config.ts.
RUN printf 'server {\n\
    listen 80;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
\n\
    # Use Docker'"'"'s internal DNS resolver so the "api" hostname is re-resolved\n\
    # after container restarts (avoids stale-IP 502s when the api container\n\
    # gets a new IP). valid=5s caps how long the resolved IP is cached.\n\
    resolver 127.0.0.11 valid=5s ipv6=off;\n\
    set $api_upstream http://api:8000;\n\
\n\
    # Proxy API calls to the backend service, stripping the /api prefix.\n\
    # rewrite strips /api before proxy_pass (required when proxy_pass uses a\n\
    # variable — the trailing-slash trick only works with literal upstreams).\n\
    location /api/ {\n\
        rewrite ^/api/(.*) /$1 break;\n\
        proxy_pass $api_upstream;\n\
        proxy_set_header Host $host;\n\
        proxy_set_header X-Real-IP $remote_addr;\n\
    }\n\
\n\
    # SPA routing: try the file, then the directory, then fall back to\n\
    # index.html so React Router can handle the path on the client.\n\
    # Content-hashed build assets never change → cache them forever.\n\
    location /assets/ {\n\
        add_header Cache-Control "public, max-age=31536000, immutable";\n\
        try_files $uri =404;\n\
    }\n\
\n\
    # The HTML shell must never be cached, or a new deploy (new hashed\n\
    # bundle) is not picked up until the browser heuristically expires its\n\
    # cached index.html — which silently serves a stale app.\n\
    location / {\n\
        add_header Cache-Control "no-cache";\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

# Copy built assets from the builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
