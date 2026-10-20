-- Виконати ОДИН РАЗ (Neon SQL Editor). Псевдонім гравця для зовнішніх каналів (Telegram, Google Sheets).
-- Секретна «сіль» живе лише в базі; без неї за player_ref не відновити player_id.
-- НЕ показуй значення солі в чаті/GitHub і не міняй її без потреби (зміниться вся відповідність).
CREATE TABLE IF NOT EXISTS ref_salt (
    id   INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    salt TEXT NOT NULL
);
INSERT INTO ref_salt (id, salt)
SELECT 1, md5(random()::text || clock_timestamp()::text) || md5(random()::text || txid_current()::text)
WHERE NOT EXISTS (SELECT 1 FROM ref_salt);
GRANT SELECT ON ref_salt TO n8n_monitor;
