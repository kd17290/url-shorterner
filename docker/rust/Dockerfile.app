# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM rust:1.93-slim-bookworm AS builder

# build-essential provides make+gcc+g++ needed by rdkafka cmake-build feature
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libssl-dev \
    pkg-config \
    libsasl2-dev \
    libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy workspace manifests first for layer caching.
COPY Cargo.toml Cargo.lock* ./
COPY services/rust/app-rs/Cargo.toml services/rust/app-rs/
COPY services/rust/keygen-rs/Cargo.toml services/rust/keygen-rs/
COPY services/rust/ingestion-rs/Cargo.toml services/rust/ingestion-rs/

# Stub src files so cargo can resolve the workspace without full source.
RUN mkdir -p services/rust/app-rs/src services/rust/keygen-rs/src services/rust/ingestion-rs/src \
    && echo 'fn main(){}' > services/rust/app-rs/src/main.rs \
    && echo 'fn main(){}' > services/rust/keygen-rs/src/main.rs \
    && echo 'fn main(){}' > services/rust/ingestion-rs/src/main.rs

# Pre-build dependencies (cached layer).
RUN cargo build --release -p app-rs 2>&1 | tail -5 || true

# Copy real source and rebuild only app-rs.
COPY services/rust/app-rs/src/ services/rust/app-rs/src/
RUN touch services/rust/app-rs/src/main.rs \
    && cargo build --release -p app-rs

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM debian:bookworm-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libssl3 \
    libsasl2-2 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/target/release/app-rs /usr/local/bin/app-rs

RUN useradd -r -s /bin/false appuser
USER appuser

EXPOSE 8000
CMD ["app-rs"]
