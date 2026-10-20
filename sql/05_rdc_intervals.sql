-- Розподіл інтервалів між FTD і другим депозитом (лише для когорти з дозрілим вікном 30 днів).
WITH asof AS (
    SELECT GREATEST((SELECT MAX(activity_date) FROM player_game_daily),
                    (SELECT MAX(activity_date) FROM player_cash_daily)) AS d
),
cohort AS (
    SELECT p.player_id, p.ftd_date
    FROM players p, asof
    WHERE p.ftd_date >= DATE '2026-08-10' AND p.ftd_date + 30 <= asof.d
      AND EXISTS (SELECT 1 FROM player_game_daily g
                  WHERE g.player_id = p.player_id AND g.activity_date >= p.ftd_date AND g.real_bet_amount > 0)
),
second_dep AS (
    SELECT c.player_id,
           LEAST(
               MIN(CASE WHEN d.activity_date > c.ftd_date AND d.deposit_count > 0 THEN d.activity_date END),
               MIN(CASE WHEN d.activity_date = c.ftd_date AND d.deposit_count >= 2 THEN d.activity_date END)
           ) - MAX(c.ftd_date) AS gap_days
    FROM cohort c
    LEFT JOIN player_cash_daily d ON d.player_id = c.player_id
    GROUP BY c.player_id
)
SELECT CASE WHEN gap_days IS NULL OR gap_days > 30 THEN '5: не повернувся за 30 днів'
            WHEN gap_days = 0 THEN '1: той самий день'
            WHEN gap_days <= 3 THEN '2: 1-3 дні'
            WHEN gap_days <= 7 THEN '3: 4-7 днів'
            ELSE '4: 8-30 днів' END AS interval_bucket,
       COUNT(*) AS players,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS share_pct
FROM second_dep
GROUP BY 1
ORDER BY 1;
