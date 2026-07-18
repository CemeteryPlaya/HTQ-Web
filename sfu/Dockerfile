# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile — Mediasoup SFU Server
#
# Multi-stage build:
# 1. Build TypeScript → JavaScript + compile mediasoup C++ worker
# 2. Production image with only compiled JS + runtime dependencies
#
# Mediasoup requires:
# - Python 3 (for node-gyp)
# - GCC/G++ (for C++ worker compilation)
# ─────────────────────────────────────────────────────────────────────────────

# -- Stage 1: Build --
FROM node:22-bookworm AS builder

# Optional proxy settings from host environment.
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV HTTP_PROXY=$HTTP_PROXY
ENV HTTPS_PROXY=$HTTPS_PROXY
ENV NO_PROXY=$NO_PROXY
ENV NODE_OPTIONS=--dns-result-order=ipv4first

# Mediasoup native dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    python3 \
    python3-pip \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies (layer caching)
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts=false

# Copy source and build
COPY tsconfig.json ./
COPY src/ ./src/
RUN npm run build

# -- Stage 2: Production --
FROM node:22-bookworm-slim

# Runtime dependencies for Mediasoup C++ worker
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy built artifacts and production dependencies
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./

# Mediasoup worker binary
COPY --from=builder /app/node_modules/mediasoup/worker/out/Release/mediasoup-worker \
     ./node_modules/mediasoup/worker/out/Release/

# Environment
ENV NODE_ENV=production
ENV SFU_PORT=4443
ENV NODE_OPTIONS=--dns-result-order=ipv4first

# Signaling port
EXPOSE 4443
# WebRTC media port (single-port mode via WebRtcServer)
EXPOSE 44444/udp
EXPOSE 44444/tcp

CMD ["node", "dist/server.js"]
