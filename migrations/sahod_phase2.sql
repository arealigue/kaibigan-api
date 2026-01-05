-- ========================================
-- SAHOD PLANNER PHASE 2 MIGRATION
-- ========================================
-- Run this in Supabase SQL Editor
-- Adds support for:
-- 1. payday_type column on instances (kinsenas/katapusan/single)
-- 2. Split allocation templates per envelope
-- ========================================

-- 1. Add payday_type to pay cycle instances
ALTER TABLE sahod_pay_cycle_instances 
ADD COLUMN IF NOT EXISTS payday_type TEXT DEFAULT 'single'
CHECK (payday_type IN ('single', 'kinsenas', 'katapusan'));

COMMENT ON COLUMN sahod_pay_cycle_instances.payday_type IS 
'Type of payday: single for monthly, kinsenas/katapusan for bi-monthly';

-- 2. Add split allocation template columns to envelopes
-- These store the PRO feature: different allocations per payday type
ALTER TABLE sahod_envelopes
ADD COLUMN IF NOT EXISTS kinsenas_amount NUMERIC DEFAULT NULL,
ADD COLUMN IF NOT EXISTS katapusan_amount NUMERIC DEFAULT NULL,
ADD COLUMN IF NOT EXISTS kinsenas_percentage NUMERIC DEFAULT NULL,
ADD COLUMN IF NOT EXISTS katapusan_percentage NUMERIC DEFAULT NULL;

COMMENT ON COLUMN sahod_envelopes.kinsenas_amount IS 
'PRO: Fixed allocation for kinsenas payday (first half of month)';
COMMENT ON COLUMN sahod_envelopes.katapusan_amount IS 
'PRO: Fixed allocation for katapusan payday (second half of month)';
COMMENT ON COLUMN sahod_envelopes.kinsenas_percentage IS 
'PRO: Percentage allocation for kinsenas payday';
COMMENT ON COLUMN sahod_envelopes.katapusan_percentage IS 
'PRO: Percentage allocation for katapusan payday';

-- 3. Update existing instances to have correct payday_type
-- For bi-monthly cycles, determine if kinsenas or katapusan based on period_start day
UPDATE sahod_pay_cycle_instances pci
SET payday_type = CASE 
    WHEN pc.frequency = 'bimonthly' AND 
         EXTRACT(DAY FROM pci.period_start::date) = pc.pay_day_1 THEN 'kinsenas'
    WHEN pc.frequency = 'bimonthly' AND 
         EXTRACT(DAY FROM pci.period_start::date) = pc.pay_day_2 THEN 'katapusan'
    ELSE 'single'
END
FROM sahod_pay_cycles pc
WHERE pci.pay_cycle_id = pc.id;

-- ========================================
-- VERIFICATION
-- ========================================
-- Check that columns were added:
-- SELECT column_name, data_type, column_default 
-- FROM information_schema.columns 
-- WHERE table_name = 'sahod_pay_cycle_instances' 
-- AND column_name = 'payday_type';

-- SELECT column_name, data_type 
-- FROM information_schema.columns 
-- WHERE table_name = 'sahod_envelopes' 
-- AND column_name IN ('kinsenas_amount', 'katapusan_amount');
