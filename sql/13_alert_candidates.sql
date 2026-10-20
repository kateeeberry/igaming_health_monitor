-- ПРОДАКШН-запит для n8n: кого сповіщати в Telegram.
-- Пороги затверджені: бонус-частка >= 0.75 (мін. обіг 100), чистий виграш за день >= 5000,
-- швидкий вивід (>=80% депозиту за 0-1 день, реальні ставки <= 1.5x депозиту, >= 2 цикли),
-- >= 3 акаунти на одному пристрої.
-- Рівні: HIGH = 2+ правила АБО одне з (bonus_share, fast_withdrawal, multi_account);
--        MEDIUM = лише big_win.
-- Дедуплікація: той самий гравець з тим самим рівнем не повторюється dedupe_days днів (таблиця alerts_sent).
WITH p AS (
    SELECT (SELECT MAX(activity_date) FROM player_game_daily) AS as_of,
           7     AS window_days,
           30    AS dedupe_days,
           0.75  AS bonus_share_min,
           100   AS bonus_min_stake,
           5000  AS bigwin_net_min,
           0.8   AS fw_withdraw_ratio,
           1.5   AS fw_turnover_ratio,
           2     AS fw_cycles_min,
           3     AS device_accounts_min
),
r_bonus AS (
    SELECT g.player_id, 'bonus_share' AS rule,
           ROUND(SUM(g.bonus_bet_amount) / SUM(g.real_bet_amount + g.bonus_bet_amount), 2) AS value
    FROM player_game_daily g, p
    WHERE g.activity_date BETWEEN p.as_of - p.window_days + 1 AND p.as_of
    GROUP BY g.player_id
    HAVING SUM(g.real_bet_amount + g.bonus_bet_amount) >= (SELECT bonus_min_stake FROM p)
       AND SUM(g.bonus_bet_amount) / SUM(g.real_bet_amount + g.bonus_bet_amount) >= (SELECT bonus_share_min FROM p)
),
r_bigwin AS (
    SELECT t.player_id, 'big_win' AS rule, ROUND(MAX(t.day_net), 0) AS value
    FROM (SELECT g.player_id, g.activity_date,
                 SUM(g.win_amount) - SUM(g.real_bet_amount + g.bonus_bet_amount) AS day_net
          FROM player_game_daily g, p
          WHERE g.activity_date BETWEEN p.as_of - p.window_days + 1 AND p.as_of
          GROUP BY g.player_id, g.activity_date) t
    GROUP BY t.player_id
    HAVING MAX(t.day_net) >= (SELECT bigwin_net_min FROM p)
),
dep AS (
    SELECT c.player_id, c.activity_date AS d, c.deposit_amount
    FROM player_cash_daily c, p
    WHERE c.deposit_amount > 0 AND c.activity_date BETWEEN p.as_of - p.window_days + 1 AND p.as_of
),
r_fast AS (
    SELECT dep.player_id, 'fast_withdrawal' AS rule, COUNT(*)::numeric AS value
    FROM dep
    CROSS JOIN LATERAL (SELECT COALESCE(SUM(c.withdrawal_amount), 0) AS w FROM player_cash_daily c
                        WHERE c.player_id = dep.player_id AND c.activity_date BETWEEN dep.d AND dep.d + 1) w
    CROSS JOIN LATERAL (SELECT COALESCE(SUM(g.real_bet_amount), 0) AS r FROM player_game_daily g
                        WHERE g.player_id = dep.player_id AND g.activity_date BETWEEN dep.d AND dep.d + 1) r
    WHERE w.w >= (SELECT fw_withdraw_ratio FROM p) * dep.deposit_amount
      AND r.r <= (SELECT fw_turnover_ratio FROM p) * dep.deposit_amount
    GROUP BY dep.player_id
    HAVING COUNT(*) >= (SELECT fw_cycles_min FROM p)
),
r_device AS (
    SELECT pl.player_id, 'multi_account' AS rule, dc.accounts::numeric AS value
    FROM players pl
    JOIN (SELECT device_id, COUNT(*) AS accounts FROM players GROUP BY device_id) dc USING (device_id)
    WHERE dc.accounts >= (SELECT device_accounts_min FROM p)
      AND EXISTS (SELECT 1 FROM player_game_daily g, p
                  WHERE g.player_id = pl.player_id AND g.activity_date BETWEEN p.as_of - p.window_days + 1 AND p.as_of)
),
signals AS (
    SELECT * FROM r_bonus UNION ALL SELECT * FROM r_bigwin UNION ALL SELECT * FROM r_fast UNION ALL SELECT * FROM r_device
),
agg AS (
    SELECT player_id,
           COUNT(*) AS n_rules,
           STRING_AGG(rule || '=' || value, ', ' ORDER BY rule) AS signals,
           BOOL_OR(rule <> 'big_win') AS has_strong_rule
    FROM signals
    GROUP BY player_id
),
leveled AS (
    SELECT a.*, CASE WHEN a.n_rules >= 2 OR a.has_strong_rule THEN 'HIGH' ELSE 'MEDIUM' END AS severity
    FROM agg a
)
SELECT l.player_id,
       LEFT(encode(sha256(convert_to((SELECT salt FROM ref_salt) || l.player_id, 'UTF8')), 'hex'), 12) AS player_ref,
       l.severity, l.n_rules, l.signals, TO_CHAR((SELECT as_of FROM p), 'YYYY-MM-DD') AS as_of
FROM leveled l
WHERE NOT EXISTS (
    SELECT 1 FROM alerts_sent s, p
    WHERE s.player_id = l.player_id AND s.severity = l.severity
      AND s.sent_at >= (p.as_of - p.dedupe_days)::timestamp
)
ORDER BY (l.severity = 'HIGH') DESC, l.n_rules DESC, l.player_id;
