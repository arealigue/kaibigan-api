--
-- Migration: Force users to reconfirm their Sobre income
-- Part of §5.1 Income Reconciliation Enhancement
-- Date: 2026-02-20

-- Force all users to re-confirm their current Sobre income
UPDATE sahod_pay_cycle_instances
SET 
  is_assumed = true,
  confirmed_at = NULL,
  actual_amount = NULL,
  requires_manual_reconfirm = true,
  updated_at = NOW()
WHERE confirmed_at IS NOT NULL;


UPDATE sahod_pay_cycle_instances
SET 
  is_assumed = true,
  confirmed_at = NULL,
  actual_amount = NULL,
  requires_manual_reconfirm = true,
  updated_at = NOW()
WHERE user_id = 'REPLACE-WITH-USER-ID'
  AND confirmed_at IS NOT NULL;