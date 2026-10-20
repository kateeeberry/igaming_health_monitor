-- Виконати ОДИН РАЗ у синтетичній базі (Neon SQL Editor).
-- 1) Журнал відправлених алертів (щоб не слати одне й те саме щодня).
-- 2) Окрема роль для n8n: читає лише потрібні таблиці (БЕЗ ground_truth), пише лише в alerts_sent.
-- ПАРОЛЬ ЗАДАЙ САМА замість <ПРИДУМАЙ_ПАРОЛЬ> і нікому не показуй (ні в чат, ні в GitHub).
CREATE TABLE IF NOT EXISTS alerts_sent (
    alert_id    BIGSERIAL PRIMARY KEY,
    player_id   VARCHAR(20) NOT NULL REFERENCES players(player_id),
    severity    VARCHAR(10) NOT NULL CHECK (severity IN ('HIGH', 'MEDIUM')),
    signals     TEXT NOT NULL,
    sent_at     TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_alerts_sent_player ON alerts_sent (player_id, severity, sent_at);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'n8n_monitor') THEN
        CREATE ROLE n8n_monitor LOGIN PASSWORD '<ПРИДУМАЙ_ПАРОЛЬ>';
    END IF;
END $$;

GRANT SELECT ON players, player_game_daily, player_cash_daily, daily_performance TO n8n_monitor;
GRANT SELECT, INSERT ON alerts_sent TO n8n_monitor;
GRANT USAGE, SELECT ON SEQUENCE alerts_sent_alert_id_seq TO n8n_monitor;
-- ground_truth навмисно НЕ видається: правила не мають бачити «правильні відповіді».
