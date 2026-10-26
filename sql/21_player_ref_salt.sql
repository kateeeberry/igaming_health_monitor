-- Run ONCE (Neon SQL Editor). Player pseudonym for external channels (Telegram, Google Sheets).
-- The secret "salt" lives only in the database; without it player_id cannot be recovered from player_ref.
-- Do NOT show the salt value in chat/GitHub and do not change it without need (the whole mapping would change).
CREATE TABLE IF NOT EXISTS ref_salt (
    id   INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    salt TEXT NOT NULL
);
INSERT INTO ref_salt (id, salt)
SELECT 1, md5(random()::text || clock_timestamp()::text) || md5(random()::text || txid_current()::text)
WHERE NOT EXISTS (SELECT 1 FROM ref_salt);
GRANT SELECT ON ref_salt TO n8n_monitor;
