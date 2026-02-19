-- Migration: Add is_admin column to profiles
-- Date: February 20, 2026
-- Purpose: Enable admin dashboard access control
-- Related Doc: /docs/redesign/ADMIN_DASHBOARD_UI_DESIGN.md

-- Add is_admin flag to profiles table
ALTER TABLE profiles
ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;

-- Add comment for documentation
COMMENT ON COLUMN profiles.is_admin IS 
  'Admin flag for /admin dashboard access. Set manually via Supabase SQL editor. No UI to grant admin.';

-- IMPORTANT: After running this migration, manually set admin(s):
-- UPDATE profiles SET is_admin = TRUE WHERE id = 'your-admin-user-id';
-- OR
-- UPDATE profiles SET is_admin = TRUE WHERE email = 'admin@kabanko.app';
