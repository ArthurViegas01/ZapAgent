# Custom Evolution API image with updated Baileys.
#
# Evolution API v2.2.3 ships with an old @whiskeysockets/baileys build that
# uses outdated WhatsApp noise-protocol keys (hardcoded in Baileys source).
# WhatsApp rotates / updates these periodically; old builds fail silently at
# the noise handshake — WebSocket 101 succeeds but the encrypted handshake
# never completes and no QR is generated.
#
# This Dockerfile extends the official image and installs the latest Baileys
# that is still API-compatible with Evolution 2.2.x (same major export shape).
# --legacy-peer-deps is required because Evolution pins some peer deps to
# ranges that don't include the latest Baileys.

FROM atendai/evolution-api:latest

WORKDIR /evolution

# Install latest Baileys (noise-protocol keys are bundled in the package).
# If a version breaks Evolution's internal imports, pin to a specific tag,
# e.g. @whiskeysockets/baileys@6.7.9
RUN apk add --no-cache git 2>/dev/null || (apt-get update -qq && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*) || true

# Baileys 7.x+ switched to pure ESM which breaks Evolution 2.2.x (uses require()).
# Pin to the last CJS-compatible release in the 6.x line.
RUN npm install @whiskeysockets/baileys@6.7.9 \
        --legacy-peer-deps \
        --no-fund \
        --no-audit \
        --prefer-online \
    && node -e "console.log('Baileys updated to ' + require('@whiskeysockets/baileys/package.json').version)"
