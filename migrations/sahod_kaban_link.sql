-- Migration: Link Sahod Planner to Kaban Transactions
-- Date: 2026-01-26
-- Purpose: Add sahod_instance_id column to kaban_transactions to link 
--          confirmed salary income with the pay cycle instance

-- Add sahod_instance_id column to kaban_transactions
-- This links income transactions created from Sahod confirmation
ALTER TABLE kaban_transactions
ADD COLUMN IF NOT EXISTS sahod_instance_id UUID REFERENCES sahod_pay_cycle_instances(id) ON DELETE SET NULL;

-- Create index for efficient lookup
CREATE INDEX IF NOT EXISTS idx_kaban_transactions_sahod_instance 
ON kaban_transactions(sahod_instance_id) 
WHERE sahod_instance_id IS NOT NULL;

-- Add comment
COMMENT ON COLUMN kaban_transactions.sahod_instance_id IS 
'Links income transaction to Sahod pay cycle instance when created via salary confirmation';
