-- Єдиний payload для тижневого звіту (одним рядком JSON): метрики, RDC D7, аномалії RTP.
-- Тиждень = 7 днів від 2026-08-10 (week_num). RDC D7: когорта за тижнем FTD, лише дозріла (ftd+7 <= остання дата).
WITH metrics AS (
WITH wk AS (
    SELECT week_num,
           SUM(bet_amount)                                             AS stake,
           SUM(win_amount)                                             AS win,
           SUM(ggr)                                                    AS ggr,
           SUM(total_bets_count)                                       AS bets,
           ROUND(100.0 * SUM(win_amount) / NULLIF(SUM(bet_amount), 0), 2)           AS rtp_pct,
           ROUND(100.0 * SUM(ggr) / NULLIF(SUM(bet_amount), 0), 2)                  AS ggr_margin_pct,
           ROUND(SUM(bet_amount) / NULLIF(SUM(total_bets_count), 0), 2)             AS avg_bet,
           ROUND(100.0 * SUM(bonus_bet_amount) / NULLIF(SUM(bet_amount), 0), 2)     AS bonus_share_pct
    FROM daily_performance
    GROUP BY week_num
),
up AS (
    SELECT ((activity_date - DATE '2026-08-10') / 7 + 1) AS week_num,
           COUNT(DISTINCT player_id) AS active_players
    FROM player_game_daily
    GROUP BY 1
),
cur  AS (SELECT w.*, u.active_players FROM wk w JOIN up u USING (week_num)
         WHERE w.week_num = (SELECT MAX(week_num) FROM wk)),
prev AS (SELECT w.*, u.active_players FROM wk w JOIN up u USING (week_num)
         WHERE w.week_num = (SELECT MAX(week_num) FROM wk) - 1)
SELECT m.metric,
       m.prev_value,
       m.cur_value,
       ROUND(m.cur_value - m.prev_value, 2) AS abs_change,
       ROUND(100.0 * (m.cur_value - m.prev_value) / NULLIF(m.prev_value, 0), 1) AS pct_change
FROM cur c, prev p,
     LATERAL (VALUES
        ('ggr',             p.ggr::numeric,            c.ggr::numeric),
        ('rtp_pct',         p.rtp_pct,                 c.rtp_pct),
        ('stake',           p.stake::numeric,          c.stake::numeric),
        ('bets_count',      p.bets::numeric,           c.bets::numeric),
        ('avg_bet',         p.avg_bet,                 c.avg_bet),
        ('active_players',  p.active_players::numeric, c.active_players::numeric),
        ('bonus_share_pct', p.bonus_share_pct,         c.bonus_share_pct),
        ('ggr_margin_pct',  p.ggr_margin_pct,          c.ggr_margin_pct)
     ) AS m(metric, prev_value, cur_value)
),
asof AS (SELECT MAX(activity_date) AS d FROM player_game_daily),
cohort AS (
    SELECT p.player_id, p.ftd_date, ((p.ftd_date - DATE '2026-08-10') / 7 + 1) AS ftd_week
    FROM players p, asof
    WHERE p.ftd_date >= DATE '2026-08-10' AND p.ftd_date + 7 <= asof.d
      AND EXISTS (SELECT 1 FROM player_game_daily g
                  WHERE g.player_id = p.player_id AND g.activity_date >= p.ftd_date AND g.real_bet_amount > 0)
),
ret AS (
    SELECT c.ftd_week, c.player_id,
           BOOL_OR(d.deposit_count > 0 AND d.activity_date > c.ftd_date AND d.activity_date <= c.ftd_date + 7
                   OR d.deposit_count >= 2 AND d.activity_date = c.ftd_date) AS returned
    FROM cohort c LEFT JOIN player_cash_daily d ON d.player_id = c.player_id
    GROUP BY c.ftd_week, c.player_id
),
rdc AS (
    SELECT ftd_week, COUNT(*) AS cohort_size,
           ROUND(100.0 * COUNT(*) FILTER (WHERE returned) / COUNT(*), 1) AS rdc_d7_pct
    FROM ret GROUP BY ftd_week
),
rdc2 AS (SELECT * FROM rdc WHERE ftd_week >= (SELECT MAX(ftd_week) FROM rdc) - 1),
anom AS (
WITH d AS (
    SELECT report_date, game_category, rtp_pct, ggr
    FROM daily_performance
),
mx AS (SELECT MAX(report_date) AS as_of FROM d),
base AS (
    SELECT game_category, AVG(rtp_pct) AS mean_rtp, STDDEV_SAMP(rtp_pct) AS sd_rtp
    FROM d, mx
    WHERE report_date <= as_of - 14 AND report_date > as_of - 14 - 56
    GROUP BY game_category
)
SELECT d.report_date, d.game_category, d.rtp_pct, d.ggr,
       ROUND(b.mean_rtp, 2) AS base_mean_rtp, ROUND(b.sd_rtp, 2) AS base_sd,
       ROUND((d.rtp_pct - b.mean_rtp) / NULLIF(b.sd_rtp, 0), 1) AS z_score
FROM d
JOIN base b USING (game_category), mx
WHERE d.report_date > mx.as_of - 14
  AND ABS((d.rtp_pct - b.mean_rtp) / NULLIF(b.sd_rtp, 0)) >= 3
ORDER BY ABS((d.rtp_pct - b.mean_rtp) / NULLIF(b.sd_rtp, 0)) DESC
)
SELECT json_build_object(
    'period_end', (SELECT d FROM asof)::text,
    'metrics', (SELECT json_agg(m ORDER BY m.metric) FROM metrics m),
    'rdc_d7_by_ftd_week', (SELECT json_agg(r ORDER BY r.ftd_week) FROM rdc2 r),
    'rtp_daily_anomalies', COALESCE((SELECT json_agg(x) FROM (SELECT * FROM anom LIMIT 5) x), '[]'::json)
)::text AS payload;
