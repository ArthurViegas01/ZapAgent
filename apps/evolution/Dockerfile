# Custom Evolution API image with updated Baileys + @lid sender_pn intercept.
#
# Two patches on top of atendai/evolution-api:latest:
#
# 1. Baileys upgrade. Evolution API v2.2.3 ships with an old
#    @whiskeysockets/baileys build whose hardcoded WhatsApp noise-protocol
#    keys are stale. WebSocket 101 succeeds but the encrypted handshake
#    never completes and no QR is generated. Pinning to 6.7.9 (the last
#    CJS-compatible Baileys release) restores the handshake.
#
# 2. @lid sender_pn intercept. Modern Brazilian WA accounts use the
#    `@lid` privacy JID; Evolution drops the `sender_pn` mapping field
#    from its webhook payload, so the API can't translate the JID back
#    to a real phone. Baileys still logs `sender_pn` to stdout, though.
#    lid_pipe.py runs Evolution as a child process, mirrors its stdout
#    to /dev/stdout (so Railway logs are preserved), and writes
#    `lid_pn:{message_id}` to Redis with a 24h TTL. The API reads that
#    key when an inbound JID ends in `@lid`. See apps/evolution/lid_pipe.py
#    docstring for the full design.

FROM atendai/evolution-api:latest

WORKDIR /evolution

# git: Baileys install. python3 + py3-redis: lid_pipe.py runtime.
# We install redis-py via the distro package manager (NOT pip) because the
# upstream evolution-api:latest base is Alpine with a Python 3.12 build
# whose pyexpat module fails to load ("symbol not found: XML_SetAllocTracker-
# ActivationThreshold") — pip itself is broken in the image, but the
# system-wide py3-redis package installs cleanly via apk.
RUN (apk add --no-cache git python3 py3-redis 2>/dev/null) \
 || (apt-get update -qq \
     && apt-get install -y --no-install-recommends git python3 python3-redis \
     && rm -rf /var/lib/apt/lists/*) \
 || true

# Baileys 7.x+ switched to pure ESM which breaks Evolution 2.2.x (uses require()).
# Pin to the last CJS-compatible release in the 6.x line.
RUN npm install @whiskeysockets/baileys@6.7.9 \
        --legacy-peer-deps \
        --no-fund \
        --no-audit \
        --prefer-online \
    && node -e "console.log('Baileys updated to ' + require('@whiskeysockets/baileys/package.json').version)"

# @lid sender_pn intercept. Runs Evolution as a subprocess and side-channels
# (message_id, sender_pn) pairs into Redis. See lid_pipe.py docstring.
COPY lid_pipe.py /usr/local/bin/lid_pipe.py
RUN chmod +x /usr/local/bin/lid_pipe.py

# Wrap the original entrypoint (which we captured via `docker inspect` on
# the upstream image) through lid_pipe. The script becomes PID 1; Evolution
# becomes its child. Signal forwarding keeps Railway's graceful shutdown
# working unchanged.
ENTRYPOINT ["python3", "/usr/local/bin/lid_pipe.py", \
            "/bin/bash", "-c", \
            ". ./Docker/scripts/deploy_database.sh && npm run start:prod"]
