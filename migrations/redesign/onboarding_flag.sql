-- Migration: Add has_completed_onboarding flag to profiles
-- Part of §8 Onboarding redesign
-- Date: 2026-02-19

ALTER TABLE profiles 
ADD COLUMN IF NOT EXISTS has_completed_onboarding BOOLEAN DEFAULT FALSE;

-- Back-fill: Mark existing users who already have pay_cycle_type set as onboarded
-- This prevents existing active users from being forced into onboarding
UPDATE profiles 
SET has_completed_onboarding = TRUE 
WHERE pay_cycle_type IS NOT NULL;

-- Also mark users who have any transactions as implicitly onboarded
UPDATE profiles 
SET has_completed_onboarding = TRUE 
WHERE id IN (
  SELECT DISTINCT user_id FROM kaban_transactions
) AND has_completed_onboarding = FALSE;
