-- ============================================================================
-- §5.1 Income Reconciliation Enhancement
-- Adds requires_manual_reconfirm flag for orphan handling
-- When a linked Kaban income tx is deleted, this flag is set to true,
-- requiring the user to manually re-confirm income in Sobre.
-- ============================================================================

ALTER TABLE sahod_pay_cycle_instances
ADD COLUMN IF NOT EXISTS requires_manual_reconfirm BOOLEAN DEFAULT false;

COMMENT ON COLUMN sahod_pay_cycle_instances.requires_manual_reconfirm IS
  'Set to true when a linked Kaban income tx is deleted, requiring user to manually re-confirm income in Sobre';
