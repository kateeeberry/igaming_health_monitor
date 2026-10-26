-- DEVELOPMENT ONLY: rules from 10_abuse_rules.sql + evaluation against ground_truth in one script (temp table flagged).
DROP TABLE IF EXISTS flagged; CREATE TEMP TABLE flagged AS -- Suspicious behavior detection rules. DETERMINISTIC: ground_truth is NOT used here.
-- Thresholds are at the top (CTE p); in a real project they would be moved to a YAML config.
-- window_days: 7 for the daily alert run; 70 to evaluate the rules over the whole history.
WITH p AS (
    SELECT (SELECT MAX(activity_date) FROM player_game_daily) AS as_of,
           70    AS window_days,
           0.75  AS bonus_share_min,      -- share of bonus bets
           100   AS bonus_min_stake,      -- minimum stake volume for this rule
           5000  AS bigwin_net_min,       -- net win per day (win - stake)
           0.8   AS fw_withdraw_ratio,    -- withdrawal >= 80% of the deposit within 0-1 days
           1.5   AS fw_turnover_ratio,    -- real stakes <= 1.5x the deposit
           2     AS fw_cycles_min,        -- minimum number of cycles
           3     AS device_accounts_min   -- accounts on one device
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
;
-- DEVELOPMENT ONLY: evaluation of the rules against ground_truth (this table is not used in the n8n workflows).
-- Insert the 10_abuse_rules.sql query in place of <<RULES>> or run it via a view/psql \i.
-- Here: a simplified approach -- we run 10_abuse_rules as a CTE result in a temporary table.
SELECT t.pattern,
       COUNT(*) AS players,
       COUNT(*) FILTER (WHERE f.player_id IS NOT NULL) AS flagged_any,
       COUNT(*) FILTER (WHERE f.n_rules >= 2) AS flagged_2plus,
       ROUND(100.0 * COUNT(*) FILTER (WHERE f.player_id IS NOT NULL) / COUNT(*), 1) AS flagged_pct
FROM ground_truth t
LEFT JOIN flagged f USING (player_id)
GROUP BY t.pattern
ORDER BY BOOL_OR(t.is_abuser) DESC, t.pattern;

SELECT 'false_positives_normal_flagged' AS k, COUNT(*) FROM flagged f JOIN ground_truth t USING (player_id) WHERE t.pattern='normal'
UNION ALL SELECT 'total_flagged', COUNT(*) FROM flagged
UNION ALL SELECT 'flagged_abusers', COUNT(*) FROM flagged f JOIN ground_truth t USING (player_id) WHERE t.is_abuser
UNION ALL SELECT 'flagged_2plus_nonabuser', COUNT(*) FROM flagged f JOIN ground_truth t USING (player_id) WHERE NOT t.is_abuser AND f.n_rules>=2;
SELECT t.pattern, f.signals FROM flagged f JOIN ground_truth t USING (player_id) WHERE t.pattern='normal' LIMIT 8;
