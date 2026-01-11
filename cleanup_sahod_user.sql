-- ============================================================================
-- CLEANUP SAHOD DATA FOR SPECIFIC USER
-- ============================================================================
-- Instructions: Replace the user_id below with the target user's UUID
-- Run this in Supabase SQL Editor to reset Sahod Planner for this user
-- ============================================================================

-- SET YOUR TARGET USER ID HERE:
DO $$
DECLARE
  target_user_id UUID := '9f6eb51a-a916-4cf3-99ab-224970b8ea86';
BEGIN

  -- 1. First: Unlink any Kaban transactions from Sahod envelopes
  -- (Must happen before deleting envelopes due to FK constraint)
  UPDATE kaban_transactions 
  SET sahod_envelope_id = NULL 
  WHERE user_id = target_user_id 
    AND sahod_envelope_id IS NOT NULL;

  -- 2. Delete sahod_allocations (references both envelopes and instances)
  DELETE FROM sahod_allocations 
  WHERE user_id = target_user_id;

  -- 3. Delete sahod_pay_cycle_instances (references pay_cycles)
  DELETE FROM sahod_pay_cycle_instances 
  WHERE user_id = target_user_id;

  -- 4. Delete sahod_envelopes (now safe - no FKs pointing to it)
  DELETE FROM sahod_envelopes 
  WHERE user_id = target_user_id;

  -- 5. Delete sahod_pay_cycles (now safe - instances deleted)
  DELETE FROM sahod_pay_cycles 
  WHERE user_id = target_user_id;

  RAISE NOTICE 'Sahod data cleaned up for user: %', target_user_id;

END $$;

-- Verify cleanup (update the user_id here too if you changed it above)
SELECT 'sahod_pay_cycles' as table_name, COUNT(*) as remaining 
FROM sahod_pay_cycles WHERE user_id = '9f6eb51a-a916-4cf3-99ab-224970b8ea86'
UNION ALL
SELECT 'sahod_pay_cycle_instances', COUNT(*) 
FROM sahod_pay_cycle_instances WHERE user_id = '9f6eb51a-a916-4cf3-99ab-224970b8ea86'
UNION ALL
SELECT 'sahod_envelopes', COUNT(*) 
FROM sahod_envelopes WHERE user_id = '9f6eb51a-a916-4cf3-99ab-224970b8ea86'
UNION ALL
SELECT 'sahod_allocations', COUNT(*) 
FROM sahod_allocations WHERE user_id = '9f6eb51a-a916-4cf3-99ab-224970b8ea86';
