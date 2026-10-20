-- Правила виявлення підозрілої поведінки. ДЕТЕРМІНОВАНІ: ground_truth тут НЕ використовується.
-- Пороги на початку (CTE p), у проєкті їх буде перенесено в YAML-конфіг.
-- window_days: 7 для щоденного запуску алертів; 70 -- для оцінки правил на всій історії.
WITH p AS (
    SELECT (SELECT MAX(activity_date) FROM player_game_daily) AS as_of,
           70    AS window_days,
           0.75  AS bonus_share_min,      -- частка бонусних ставок
           100   AS bonus_min_stake,      -- мінімальний обсяг ставок для цього правила
           5000  AS bigwin_net_min,       -- чистий виграш за день (win - stake)
           0.8   AS fw_withdraw_ratio,    -- вивід >= 80% депозиту за 0-1 день
           1.5   AS fw_turnover_ratio,    -- реальні ставки <= 1.5x депозиту
           2     AS fw_cycles_min,        -- мінімум циклів
           3     AS device_accounts_min   -- акаунтів на одному пристрої
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
    SELECT g.player_id, 'big_win' AS rule,
           ROUND(MAX(day_net), 0) AS value
    FROM (SELECT g.player_id, g.activity_date,
                 SUM(g.win_amount) - SUM(g.real_bet_amount + g.bonus_bet_amount) AS day_net
          FROM player_game_daily g, p
          WHERE g.activity_date BETWEEN p.as_of - p.window_days + 1 AND p.as_of
          GROUP BY g.player_id, g.activity_date) g
    GROUP BY g.player_id
    HAVING MAX(day_net) >= (SELECT bigwin_net_min FROM p)
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
),
signals AS (
    SELECT * FROM r_bonus UNION ALL SELECT * FROM r_bigwin UNION ALL SELECT * FROM r_fast UNION ALL SELECT * FROM r_device
)
SELECT player_id,
       COUNT(*) AS n_rules,
       STRING_AGG(rule || '=' || value, ', ' ORDER BY rule) AS signals
FROM signals
GROUP BY player_id
ORDER BY n_rules DESC, player_id;
