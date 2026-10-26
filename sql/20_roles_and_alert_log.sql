-- Run ONCE in the synthetic database (Neon SQL Editor).
-- 1) Log of sent alerts (so the same thing is not sent every day).
-- 2) A separate role for n8n: reads only the required tables (WITHOUT ground_truth), writes only to alerts_sent.
-- SET THE PASSWORD YOURSELF in place of <CHOOSE_A_PASSWORD> and never share it (not in chat, not on GitHub).
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
        CREATE ROLE n8n_monitor LOGIN PASSWORD '<CHOOSE_A_PASSWORD>';
    END IF;
END $$;

GRANT SELECT ON players, player_game_daily, player_cash_daily, daily_performance TO n8n_monitor;
GRANT SELECT, INSERT ON alerts_sent TO n8n_monitor;
GRANT USAGE, SELECT ON SEQUENCE alerts_sent_alert_id_seq TO n8n_monitor;
-- ground_truth is deliberately NOT granted: the rules must not see the "correct answers".
