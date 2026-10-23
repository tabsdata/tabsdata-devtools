# Copyright 2026 Tabsdata Inc.
#
# cloudburrow's standalone storage server at a pinned commit, with our patch
# (XML ListObjectsV2 continuation tokens and x-goog-copy-source), for the
# gcslocal system. Upstream publishes no image, so tdd builds this one locally,
# for the machine's own architecture: a static Go build on multi-arch bases.
# REPOSITORY and COMMIT are passed by tdd (systems/gcslocal/backend.py).

FROM golang:1.26-alpine@sha256:27f2d3b83cfc5803c8078f8e730af0f7c431bf067afaec8f60a36fb763187cba AS build
ARG REPOSITORY
ARG COMMIT
RUN apk add --no-cache git
WORKDIR /src
RUN git init -q . \
    && git fetch -q --depth 1 "${REPOSITORY}" "${COMMIT}" \
    && git checkout -q FETCH_HEAD
COPY cloudburrow.patch /tmp/cloudburrow.patch
RUN git apply /tmp/cloudburrow.patch
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /cloudburrow-storage ./cmd/cloudburrow-storage

FROM alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f
COPY --from=build /cloudburrow-storage /usr/local/bin/cloudburrow-storage
EXPOSE 4443
ENTRYPOINT ["cloudburrow-storage", "--listen", "0.0.0.0:4443", "--allow-remote"]
