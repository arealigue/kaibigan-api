-- Migration: envelope_link_columns
-- Purpose: Add sahod_envelope_id to recurring_rules and quick_add_shortcuts
-- so they can be linked to Sobre envelopes for automatic categorization.
-- Safe to re-run (uses IF NOT EXISTS).
-- Created: February 21, 2026
-- Run this in Supabase SQL Editor

-- ============================================
-- 1. Add sahod_envelope_id to recurring_rules
-- ============================================
ALTER TABLE recurring_rules 
ADD COLUMN IF NOT EXISTS sahod_envelope_id UUID REFERENCES sahod_envelopes(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_recurring_rules_envelope ON recurring_rules(sahod_envelope_id);

-- ============================================
-- 2. Add sahod_envelope_id to quick_add_shortcuts
-- ============================================
ALTER TABLE quick_add_shortcuts 
ADD COLUMN IF NOT EXISTS sahod_envelope_id UUID REFERENCES sahod_envelopes(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_quick_add_shortcuts_envelope ON quick_add_shortcuts(sahod_envelope_id);
