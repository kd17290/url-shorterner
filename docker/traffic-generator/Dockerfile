FROM rust:1.70 AS builder

WORKDIR /build

# Copy only traffic generator files
COPY services/traffic-generator-rs/Cargo.toml ./services/traffic-generator-rs/
RUN mkdir -p services/traffic-generator-rs/src && \
    echo 'fn main(){}' > services/traffic-generator-rs/src/main.rs

# Build dependencies
RUN cd services/traffic-generator-rs && cargo build --release

# Copy actual source
COPY services/traffic-generator-rs/src ./services/traffic-generator-rs/src

# Build the binary
RUN cd services/traffic-generator-rs && cargo build --release

# Runtime image
FROM debian:bookworm-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the binary
COPY --from=builder /build/services/traffic-generator-rs/target/release/traffic-generator-rs .

# Create non-root user
RUN useradd -m -u 1000 trafficgen

USER trafficgen

CMD ["./traffic-generator-rs", \
     "--target-url", "http://app:8000", \
     "--workers", "100", \
     "--read-rps", "2000", \
     "--write-rps", "1000", \
     "--url-count", "10", \
     "--duration", "300", \
     "--warmup", "15"]
