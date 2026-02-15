-- Migration: Add consent_version column to profiles
-- Date: February 15, 2026
-- Purpose: Track which version of Terms/Privacy the user accepted.
--          When CURRENT_TERMS_VERSION is bumped in the frontend,
--          users with an older consent_version are forced to re-accept.
--
-- Related docs: /docs/legal/LEGAL_PAGES_UPDATE.md
-- Run this BEFORE deploying the frontend update.

-- Add consent_version column (default 1 for existing users who already consented)
ALTER TABLE profiles
ADD COLUMN IF NOT EXISTS consent_version INTEGER DEFAULT 1;

-- Set version 2 for all users who already consented (they accepted v1 terms,
-- but v2 is less restrictive so implicit consent is acceptable)
UPDATE profiles
SET consent_version = 2
WHERE privacy_consent = TRUE
  AND (consent_version IS NULL OR consent_version < 2);

-- Comment for future reference
COMMENT ON COLUMN profiles.consent_version IS 
  'Tracks which Terms of Service version the user accepted. Bump CURRENT_TERMS_VERSION in lib/version.ts to force re-consent.';
