-- RDC (Return Deposit Count): повернення з другим депозитом після FTD.
-- Затверджене робоче визначення:
--   когорта = гравці з FTD у вікні даних, які після FTD (включно з днем FTD) зробили >=1 ставку реальними грошима;
--   «повернувся за N днів» = другий депозит не пізніше ftd_date + N (другий депозит у день FTD = 0 днів);
--   для N беремо лише «дозрілу» когорту: ftd_date + N <= остання дата даних (інакше це не «не повернувся»).
WITH asof AS (
    SELECT GREATEST((SELECT MAX(activity_date) FROM player_game_daily),
                    (SELECT MAX(activity_date) FROM player_cash_daily)) AS d
),
cohort AS (
    SELECT p.player_id, p.ftd_date
    FROM players p, asof
    WHERE p.ftd_date >= DATE '2026-08-10' AND p.ftd_date <= asof.d
      AND EXISTS (SELECT 1 FROM player_game_daily g
                  WHERE g.player_id = p.player_id AND g.activity_date >= p.ftd_date AND g.real_bet_amount > 0)
),
second_dep AS (
    SELECT c.player_id, c.ftd_date,
           LEAST(
               MIN(CASE WHEN d.activity_date > c.ftd_date AND d.deposit_count > 0 THEN d.activity_date END),
               MIN(CASE WHEN d.activity_date = c.ftd_date AND d.deposit_count >= 2 THEN d.activity_date END)
           ) AS second_date
    FROM cohort c
    LEFT JOIN player_cash_daily d ON d.player_id = c.player_id
    GROUP BY c.player_id, c.ftd_date
),
iv AS (SELECT player_id, ftd_date, (second_date - ftd_date) AS gap_days FROM second_dep)
SELECT n.window_days,
       COUNT(*) FILTER (WHERE iv.ftd_date + n.window_days <= (SELECT d FROM asof))                          AS matured_cohort,
       COUNT(*) FILTER (WHERE iv.ftd_date + n.window_days <= (SELECT d FROM asof) AND iv.gap_days <= n.window_days) AS returned,
       ROUND(100.0 * COUNT(*) FILTER (WHERE iv.ftd_date + n.window_days <= (SELECT d FROM asof) AND iv.gap_days <= n.window_days)
             / NULLIF(COUNT(*) FILTER (WHERE iv.ftd_date + n.window_days <= (SELECT d FROM asof)), 0), 1)    AS rdc_rate_pct
FROM iv, (VALUES (1), (3), (7), (30)) AS n(window_days)
GROUP BY n.window_days
ORDER BY n.window_days;
