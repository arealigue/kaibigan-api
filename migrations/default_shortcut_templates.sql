-- ==============================================
-- MIGRATION: Default Shortcut Templates
-- ==============================================
-- Purpose: Provide system-level templates for Quick Add shortcuts
--          that get instantiated per-user during Sahod setup
-- Date: January 26, 2026
-- ==============================================

-- 1. Create default_shortcut_templates table
-- This is a SYSTEM table (not user-specific) that stores templates
CREATE TABLE IF NOT EXISTS default_shortcut_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label VARCHAR(50) NOT NULL,
    label_en VARCHAR(50) NOT NULL,
    emoji VARCHAR(10) NOT NULL,
    default_amount NUMERIC(10,2) NOT NULL,
    category_hint VARCHAR(100) NOT NULL,  -- Hint to match against expense_categories.name
    envelope_hint VARCHAR(100) NOT NULL,  -- Hint to match against sahod_envelopes.name
    display_order INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Enable RLS on default_shortcut_templates (system table - public read access)
ALTER TABLE default_shortcut_templates ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Allow authenticated users to read templates (system data)
DROP POLICY IF EXISTS "Anyone can read default templates" ON default_shortcut_templates;
CREATE POLICY "Anyone can read default templates" ON default_shortcut_templates
    FOR SELECT USING (true);

-- Note: No INSERT/UPDATE/DELETE policies - only admins can modify via service role

-- 2. Seed default templates optimized for Filipino daily expenses
-- category_hint MUST match expense_categories.name EXACTLY (case-insensitive)
-- envelope_hint is flexible - will try to match user's envelope names
DELETE FROM default_shortcut_templates; -- Clear old data first

INSERT INTO default_shortcut_templates (label, label_en, emoji, default_amount, category_hint, envelope_hint, display_order) VALUES
-- Transportation shortcuts (category: Transportation)
('Jeep', 'Jeep Fare', '🚌', 15, 'Transportation', 'transpo,transportation,pamasahe,commute', 1),
('Grab', 'Grab/Angkas', '🚗', 100, 'Transportation', 'transpo,transportation,pamasahe,commute', 5),

-- Food shortcuts (categories: Milk Tea, Food Delivery)
('Kape', 'Coffee', '☕', 50, 'Milk Tea', 'food,pagkain,kain,meals', 2),
('Lunch', 'Lunch', '🍚', 100, 'Food Delivery', 'food,pagkain,kain,meals', 3),
('Milk Tea', 'Milk Tea', '🧋', 120, 'Milk Tea', 'food,pagkain,kain,meals', 6),

-- Bills/Utilities shortcuts (category: Load)
('Load', 'Mobile Load', '📱', 50, 'Load', 'bills,bayarin,utilities,kuryente', 4)

ON CONFLICT DO NOTHING;

-- 3. Add is_system_default column to quick_add_shortcuts
-- Marks shortcuts that were auto-created from templates
ALTER TABLE quick_add_shortcuts 
ADD COLUMN IF NOT EXISTS is_system_default BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN quick_add_shortcuts.is_system_default IS 
'True if this shortcut was auto-created from default_shortcut_templates';

-- 4. Create envelope_category_mappings table (if not exists)
-- Links categories to envelopes for automatic expense routing
CREATE TABLE IF NOT EXISTS envelope_category_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    envelope_id UUID NOT NULL REFERENCES sahod_envelopes(id) ON DELETE CASCADE,
    category_id UUID NOT NULL REFERENCES expense_categories(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Each category can only map to ONE envelope per user
    UNIQUE(user_id, category_id)
);

-- Enable RLS
ALTER TABLE envelope_category_mappings ENABLE ROW LEVEL SECURITY;

-- RLS Policies
DROP POLICY IF EXISTS "Users can view own mappings" ON envelope_category_mappings;
CREATE POLICY "Users can view own mappings" ON envelope_category_mappings
    FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can create own mappings" ON envelope_category_mappings;
CREATE POLICY "Users can create own mappings" ON envelope_category_mappings
    FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own mappings" ON envelope_category_mappings;
CREATE POLICY "Users can update own mappings" ON envelope_category_mappings
    FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete own mappings" ON envelope_category_mappings;
CREATE POLICY "Users can delete own mappings" ON envelope_category_mappings
    FOR DELETE USING (auth.uid() = user_id);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_envelope_category_mappings_user ON envelope_category_mappings(user_id);
CREATE INDEX IF NOT EXISTS idx_envelope_category_mappings_envelope ON envelope_category_mappings(envelope_id);
CREATE INDEX IF NOT EXISTS idx_envelope_category_mappings_category ON envelope_category_mappings(category_id);

-- 5. Add default envelope hint to expense_categories
-- For default categories, stores which envelope type they typically belong to
ALTER TABLE expense_categories
ADD COLUMN IF NOT EXISTS default_envelope_hint VARCHAR(100);

COMMENT ON COLUMN expense_categories.default_envelope_hint IS 
'For system categories, suggests which envelope type this category belongs to (e.g., Food, Transportation)';

-- Update default categories with hints
UPDATE expense_categories SET default_envelope_hint = 'Transportation' WHERE name = 'Transportation' AND user_id IS NULL;
UPDATE expense_categories SET default_envelope_hint = 'Food' WHERE name IN ('Food Delivery', 'Groceries', 'Milk Tea') AND user_id IS NULL;
UPDATE expense_categories SET default_envelope_hint = 'Bills' WHERE name IN ('Bills (Kuryente/Tubig)', 'Load') AND user_id IS NULL;
UPDATE expense_categories SET default_envelope_hint = 'Entertainment' WHERE name = 'Entertainment' AND user_id IS NULL;
UPDATE expense_categories SET default_envelope_hint = 'Health' WHERE name = 'Medicine' AND user_id IS NULL;

-- ==============================================
-- VERIFICATION
-- ==============================================
-- Run these queries to verify migration:

-- SELECT * FROM default_shortcut_templates ORDER BY display_order;
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'quick_add_shortcuts';
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'expense_categories';
