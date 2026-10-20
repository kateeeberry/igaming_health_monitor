-- Зворотний пошук для власниці бази: з player_ref (із Telegram/Sheets) знайти player_id.
-- Виконується в SQL Editor під власником, НЕ через n8n. Підстав свій ref замість 'abc123def456'.
SELECT p.player_id
FROM players p, ref_salt s
WHERE LEFT(encode(sha256(convert_to(s.salt || p.player_id, 'UTF8')), 'hex'), 12) = 'abc123def456';
