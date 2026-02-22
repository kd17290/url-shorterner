-- Initialize test database
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create URL sequence for testing
CREATE SEQUENCE IF NOT EXISTS url_id_sequence
    START WITH 1000000
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- Create URLs table for testing
CREATE TABLE IF NOT EXISTS urls (
    id SERIAL PRIMARY KEY,
    short_code VARCHAR(10) UNIQUE NOT NULL,
    original_url TEXT NOT NULL,
    clicks INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_urls_short_code ON urls(short_code);
CREATE INDEX IF NOT EXISTS idx_urls_created_at ON urls(created_at DESC);

-- Create allocation records table for testing
CREATE TABLE IF NOT EXISTS id_allocation_records (
    id SERIAL PRIMARY KEY,
    start_id BIGINT NOT NULL,
    end_id BIGINT NOT NULL,
    range_size INTEGER NOT NULL,
    allocated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    source VARCHAR(50) NOT NULL DEFAULT 'redis_sentinel',
    UNIQUE(start_id, end_id)
);

-- Create indexes for allocation records
CREATE INDEX IF NOT EXISTS idx_allocation_records_range 
ON id_allocation_records(start_id, end_id);
CREATE INDEX IF NOT EXISTS idx_allocation_records_allocated_at 
ON id_allocation_records(allocated_at DESC);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO test_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO test_user;
