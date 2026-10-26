CREATE EXTENSION IF NOT EXISTS timescaledb;
SELECT create_hypertable('deal_events', by_range('event_time'), if_not_exists => TRUE);
