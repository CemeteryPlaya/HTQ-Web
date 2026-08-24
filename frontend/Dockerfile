# ─── Frontend (Vite React SPA) ──────────────────────────────────────────────
# Multi-stage: build with Node 20, then copy dist into a tiny Alpine image
# that copies files into a shared volume at runtime.
# ─────────────────────────────────────────────────────────────────────────────

FROM node:20-alpine AS builder
WORKDIR /app

# Install build dependencies for native modules (e.g. sharp)
RUN apk add --no-cache python3 make g++

# Copy lock file first for better layer caching
COPY package.json package-lock.json ./
RUN npm ci --legacy-peer-deps --no-audit --no-fund

COPY . .

# API calls go to relative /api/; nginx routes them to FastAPI services.
ARG VITE_API_BASE_URL=/api/
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# SFU signaling — use relative /ws/sfu/ so nginx handles it
ARG VITE_SFU_URL=
ENV VITE_SFU_URL=$VITE_SFU_URL

# WebTransport — leave empty to disable
ARG VITE_WEBTRANSPORT_URL=
ENV VITE_WEBTRANSPORT_URL=$VITE_WEBTRANSPORT_URL

# Среда и политика подмен (src/lib/fallback.ts). Значение вшивается в бандл на
# сборке — Vite подставляет import.meta.env.* статически, менять его в рантайме
# нечем. Поэтому staging-сборка отличается от прод-сборки ровно этим аргументом.
ARG VITE_HTQ_ENV=production
ENV VITE_HTQ_ENV=$VITE_HTQ_ENV
ARG VITE_FALLBACK_MODE=
ENV VITE_FALLBACK_MODE=$VITE_FALLBACK_MODE

RUN npm run build

# ── Second stage: just holds the built dist files ──
FROM alpine:3.20
COPY --from=builder /app/dist /dist
# Copy files into the shared volume mount point on startup
ENTRYPOINT ["sh", "-c", "cp -r /dist/. /html/ && echo '[frontend] dist copied to /html — ready'"]
