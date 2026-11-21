BEGIN;
-- Deployment-wide Bot API incompatibilities. Only registered template IDs are written.
CREATE TABLE IF NOT EXISTS math_template_png_fallbacks (
    template_id text PRIMARY KEY
);
ALTER TABLE math_template_png_fallbacks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON math_template_png_fallbacks FROM PUBLIC;
DO $$
BEGIN
 IF EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN
  REVOKE ALL ON math_template_png_fallbacks FROM anon;
 END IF;
 IF EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN
  REVOKE ALL ON math_template_png_fallbacks FROM authenticated;
 END IF;
END $$;
COMMIT;
