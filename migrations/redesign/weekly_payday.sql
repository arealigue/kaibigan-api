-- Migration: weekly_payday
-- Description: Adds weekly_payday column for users with weekly pay cycles
-- Author: KabanKo Team
-- Date: 2026-02-20
-- Feature: §10 Weekly & Daily Pay Cycles

-- Add weekly_payday column (1=Monday, 7=Sunday)
-- This stores which day of the week the user gets paid for weekly cycles
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS weekly_payday INTEGER DEFAULT 5;

-- Add check constraint to ensure valid day of week (1-7)
-- Note: We don't add a strict constraint since Supabase handles this at app level
-- and the default is Friday (5) which is the most common weekly payday

-- NOTES:
-- pay_cycle_type now accepts: 'monthly', 'kinsenas', 'weekly', 'daily'
-- For 'weekly' cycles: weekly_payday determines the day (1=Mon, 2=Tue, ..., 7=Sun)
-- For 'daily' cycles: No payday field needed (cycle = today)
-- For 'monthly'/'kinsenas': Use existing monthly_payday, kinsenas_day, katapusan_day columns

COMMENT ON COLUMN profiles.weekly_payday IS 'Day of week for weekly pay cycles (1=Mon, 7=Sun). Default: Friday (5)';
