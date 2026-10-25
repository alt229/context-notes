# Caddy with the Cloudflare DNS plugin: gets a Let's Encrypt certificate for $DOMAIN through a DNS challenge
# (no port needs to be open to the internet) and renews it by itself.
FROM caddy:2-builder AS builder
RUN xcaddy build --with github.com/caddy-dns/cloudflare

FROM caddy:2
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
