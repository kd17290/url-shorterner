FROM rust:1.80 as builder

WORKDIR /build

# Copy workspace files
COPY Cargo.toml Cargo.lock ./
COPY services/traffic-generator-rs/Cargo.toml ./services/traffic-generator-rs/

# Create dummy main.rs for dependency caching
RUN mkdir -p services/traffic-generator-rs/src && \
    echo 'fn main(){}' > services/traffic-generator-rs/src/main.rs

# Build dependencies
RUN cargo build --release -p traffic-generator-rs

# Copy actual source
COPY services/traffic-generator-rs/src ./services/traffic-generator-rs/src

# Build the binary
RUN touch services/traffic-generator-rs/src/main.rs && \
    cargo build --release -p traffic-generator-rs

# Runtime image
FROM debian:bookworm-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the binary
COPY --from=builder /build/target/release/traffic-generator-rs .

# Create non-root user
RUN useradd -m -u 1000 trafficgen

USER trafficgen

EXPOSE 8080

CMD ["./traffic-generator-rs", "--help"]
