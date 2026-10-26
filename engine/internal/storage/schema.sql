CREATE TABLE IF NOT EXISTS fuse_leadership (
 id boolean PRIMARY KEY DEFAULT true CHECK (id),
 generation bigint NOT NULL DEFAULT 0,
 sequence bigint NOT NULL DEFAULT 0,
 journal_hash text NOT NULL DEFAULT ''
);
INSERT INTO fuse_leadership(id) VALUES(true) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS fuse_journal (
 sequence bigint PRIMARY KEY,
 command_key text NOT NULL UNIQUE,
 event jsonb NOT NULL,
 event_encoded bytea
);
CREATE TABLE IF NOT EXISTS fuse_postings (
 sequence bigint NOT NULL REFERENCES fuse_journal(sequence),
 ordinal integer NOT NULL,
 account text NOT NULL,
 asset text NOT NULL CHECK (asset IN ('USDC','USDC_RESERVATION')),
 delta bigint NOT NULL CHECK (delta <> 0),
 PRIMARY KEY(sequence,ordinal)
);
CREATE TABLE IF NOT EXISTS fuse_outbox (
 sequence bigint NOT NULL REFERENCES fuse_journal(sequence),
 account text NOT NULL,
 payload jsonb NOT NULL,
 PRIMARY KEY(sequence,account)
);
CREATE TABLE IF NOT EXISTS fuse_snapshot (
 id boolean PRIMARY KEY DEFAULT true CHECK (id),
 sequence bigint NOT NULL,
 state jsonb NOT NULL,
 state_encoded bytea
);
CREATE OR REPLACE FUNCTION fuse_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'FUSE journal, postings and outbox are append only'; END $$;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='fuse_journal_immutable') THEN
 CREATE TRIGGER fuse_journal_immutable BEFORE UPDATE OR DELETE ON fuse_journal FOR EACH ROW EXECUTE FUNCTION fuse_immutable();
 CREATE TRIGGER fuse_postings_immutable BEFORE UPDATE OR DELETE ON fuse_postings FOR EACH ROW EXECUTE FUNCTION fuse_immutable();
 CREATE TRIGGER fuse_outbox_immutable BEFORE UPDATE OR DELETE ON fuse_outbox FOR EACH ROW EXECUTE FUNCTION fuse_immutable();
 END IF;
END $$;

-- JSONB rewrites nested RawMessage key order. Preserve authoritative encoded bytes
-- alongside queryable projections so journal/snapshot commitments survive recovery.
ALTER TABLE fuse_journal ADD COLUMN IF NOT EXISTS event_encoded bytea;
ALTER TABLE fuse_snapshot ADD COLUMN IF NOT EXISTS state_encoded bytea;
