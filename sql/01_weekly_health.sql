-- Weekly project health comparison: the last full week vs the previous one.
-- Source: view daily_performance (aggregate of player_game_daily) + player_game_daily for unique players.
-- Definitions (to be approved!): bet_amount = real + bonus bets; ggr = bet_amount - win_amount;
-- Weekly RTP = SUM(win)/SUM(bet_amount), not the average of daily rtp_pct.
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
     ) AS m(metric, prev_value, cur_value);
