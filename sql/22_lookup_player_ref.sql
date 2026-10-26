-- Reverse lookup for the database owner: find player_id from a player_ref (from Telegram/Sheets).
-- Run in the SQL Editor as the owner, NOT through n8n. Substitute your own ref in place of 'abc123def456'.
SELECT p.player_id
FROM players p, ref_salt s
WHERE LEFT(encode(sha256(convert_to(s.salt || p.player_id, 'UTF8')), 'hex'), 12) = 'abc123def456';
