-- The same week vs the previous one, but by game category (where the change comes from).
WITH w AS (
    SELECT week_num, game_category,
           SUM(bet_amount) AS stake, SUM(win_amount) AS win, SUM(ggr) AS ggr,
           ROUND(100.0 * SUM(win_amount) / NULLIF(SUM(bet_amount), 0), 2) AS rtp_pct
    FROM daily_performance
    GROUP BY week_num, game_category
),
mx AS (SELECT MAX(week_num) AS m FROM w)
SELECT c.game_category,
       p.ggr AS prev_ggr, c.ggr AS cur_ggr,
       ROUND(100.0 * (c.ggr - p.ggr) / NULLIF(p.ggr, 0), 1) AS ggr_pct_change,
       p.rtp_pct AS prev_rtp, c.rtp_pct AS cur_rtp,
       ROUND(c.rtp_pct - p.rtp_pct, 2) AS rtp_pp_change
FROM w c
JOIN w p ON p.game_category = c.game_category AND p.week_num = c.week_num - 1
WHERE c.week_num = (SELECT m FROM mx)
ORDER BY c.game_category;
