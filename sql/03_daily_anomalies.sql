-- Денні відхилення RTP за останні 14 днів відносно попередніх 8 тижнів (по категорії).
-- z = (rtp дня - середній rtp базового періоду) / stddev базового періоду. Показуємо |z| >= 3.
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
ORDER BY ABS((d.rtp_pct - b.mean_rtp) / NULLIF(b.sd_rtp, 0)) DESC;
