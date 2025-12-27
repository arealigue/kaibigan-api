-- Migration: 001_analytics_events
-- Purpose: Create analytics_events table for retention tracking
-- Created: December 22, 2025
-- Run this in Supabase SQL Editor

-- ============================================
-- 1. Create the analytics_events table
-- ============================================
CREATE TABLE IF NOT EXISTS analytics_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  event_name TEXT NOT NULL,
  event_properties JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast queries by user and event
CREATE INDEX IF NOT EXISTS idx_analytics_events_user_id ON analytics_events(user_id);
CREATE INDEX IF NOT EXISTS idx_analytics_events_event_name ON analytics_events(event_name);
CREATE INDEX IF NOT EXISTS idx_analytics_events_created_at ON analytics_events(created_at);

-- Composite index for common query pattern
CREATE INDEX IF NOT EXISTS idx_analytics_events_user_event 
  ON analytics_events(user_id, event_name, created_at DESC);

-- ============================================
-- 2. Enable Row Level Security (RLS)
-- ============================================
ALTER TABLE analytics_events ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only insert their own events
CREATE POLICY "Users can insert own events" 
  ON analytics_events FOR INSERT 
  WITH CHECK (auth.uid() = user_id);

-- Policy: Users can read their own events (optional, for debugging)
CREATE POLICY "Users can view own events" 
  ON analytics_events FOR SELECT 
  USING (auth.uid() = user_id);

-- Policy: Service role can read all (for admin dashboards)
-- This is automatically handled by Supabase service role

-- ============================================
-- 3. Create helper function to check if event exists
-- ============================================
CREATE OR REPLACE FUNCTION has_event(p_user_id UUID, p_event_name TEXT)
RETURNS BOOLEAN AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM analytics_events 
    WHERE user_id = p_user_id AND event_name = p_event_name
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================
-- 4. Create function to count user transactions today
-- ============================================
CREATE OR REPLACE FUNCTION count_user_transactions_today(p_user_id UUID)
RETURNS INTEGER AS $$
DECLARE
  tx_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO tx_count
  FROM kaban_transactions
  WHERE user_id = p_user_id
    AND created_at >= CURRENT_DATE
    AND created_at < CURRENT_DATE + INTERVAL '1 day';
  RETURN tx_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================
-- 5. Sample Queries for Dashboard (run manually)
-- ============================================

-- Signup completion rate (last 30 days)
-- SELECT 
--   DATE(created_at) as date,
--   COUNT(*) as signups
-- FROM analytics_events
-- WHERE event_name = 'signup_completed'
--   AND created_at >= NOW() - INTERVAL '30 days'
-- GROUP BY DATE(created_at)
-- ORDER BY date DESC;

-- First transaction rate
-- SELECT 
--   COUNT(DISTINCT CASE WHEN event_name = 'signup_completed' THEN user_id END) as signups,
--   COUNT(DISTINCT CASE WHEN event_name = 'first_transaction_logged' THEN user_id END) as first_tx,
--   ROUND(
--     COUNT(DISTINCT CASE WHEN event_name = 'first_transaction_logged' THEN user_id END)::NUMERIC /
--     NULLIF(COUNT(DISTINCT CASE WHEN event_name = 'signup_completed' THEN user_id END), 0) * 100, 1
--   ) as conversion_pct
-- FROM analytics_events
-- WHERE created_at >= NOW() - INTERVAL '30 days';

-- Day 2 return rate
-- SELECT 
--   COUNT(DISTINCT CASE WHEN event_name = 'signup_completed' THEN user_id END) as signups,
--   COUNT(DISTINCT CASE WHEN event_name = 'day_2_return' THEN user_id END) as day2_returns,
--   ROUND(
--     COUNT(DISTINCT CASE WHEN event_name = 'day_2_return' THEN user_id END)::NUMERIC /
--     NULLIF(COUNT(DISTINCT CASE WHEN event_name = 'signup_completed' THEN user_id END), 0) * 100, 1
--   ) as retention_pct
-- FROM analytics_events
-- WHERE created_at >= NOW() - INTERVAL '30 days';

COMMENT ON TABLE analytics_events IS 'Tracks user retention events: signup, first transaction, return visits';
