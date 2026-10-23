# syntax=docker/dockerfile:1.7
# The installation's front door (v4 Phase 6): Caddy serving the built front,
# the media files and the API behind it. Built by deploy/release/bundle.sh
# with the front's dist/ as the `front` build context.
ARG CADDY=caddy:2.11.7-alpine
FROM ${CADDY}
COPY --from=front . /srv/front
COPY deploy/onprem/Caddyfile /etc/caddy/Caddyfile
ARG BUILD_TENANT=""
ARG BUILD_VERSION=""
ARG BUILD_ID=""
LABEL predictive.tenant=${BUILD_TENANT} predictive.version=${BUILD_VERSION} predictive.build=${BUILD_ID}
