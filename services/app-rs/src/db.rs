use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;

pub async fn create_pool(database_url: &str) -> anyhow::Result<PgPool> {
    let pool = PgPoolOptions::new()
        .max_connections(20)
        .min_connections(2)
        .connect(database_url)
        .await?;
    Ok(pool)
}

pub async fn migrate(pool: &PgPool) -> anyhow::Result<()> {
    // Advisory lock so only one replica runs DDL when 3 instances start simultaneously.
    sqlx::query("SELECT pg_advisory_lock(12345678)")
        .execute(pool)
        .await?;

    sqlx::query(
        r#"
        CREATE TABLE IF NOT EXISTS urls (
            id          BIGSERIAL PRIMARY KEY,
            short_code  VARCHAR(20) NOT NULL UNIQUE,
            original_url TEXT NOT NULL,
            clicks      BIGINT NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        "#,
    )
    .execute(pool)
    .await?;

    sqlx::query("SELECT pg_advisory_unlock(12345678)")
        .execute(pool)
        .await?;

    Ok(())
}
