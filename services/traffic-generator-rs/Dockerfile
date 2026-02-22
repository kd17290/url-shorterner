FROM rust:1.80 as builder

WORKDIR /build

# Copy only the traffic generator files
COPY services/traffic-generator-rs/Cargo.toml ./
RUN mkdir src

# Create dummy main.rs for dependency caching
RUN echo 'fn main() {}' > src/main.rs
RUN cargo build --release

# Copy actual source
COPY services/traffic-generator-rs/src ./src
RUN touch src/main.rs && cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/target/release/traffic-generator /usr/local/bin/
CMD ["traffic-generator"]
