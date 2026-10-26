Claude
/
rivelk, Connected











































Readme · MD
# iGaming Health Monitor
 
n8n automation for an iGaming analyst: a **weekly project health report** and **daily alerts about suspicious player behavior**. It runs on synthetic data, and the mechanism is designed to be ported to a real project.
 
> All data in this repository is synthetic. There are no real players, keys or connections here.
 
## Key metrics
 
The report has three main metrics: **GGR** (revenue), **RTP** (whether the game holds its margin) and **RDC D7** (retention of new depositors). The remaining metrics (stakes, bet count, average bet, active players, bonus share, GGR margin) are supporting metrics that explain why the main ones changed.
 
## What it does
 
| Workflow | Schedule | Output |
|---|---|---|
| **Weekly health report** | every Monday 09:00 | Week-over-week metrics (GGR, RTP, stakes, bet count, average bet, active players, bonus bet share, GGR margin), RDC D7, and daily RTP anomalies. It also includes the top 3 biggest daily player wins (under pseudonyms), so that a fact can be told apart from an assumption about the cause of an anomaly. Gemini adds conclusions, with facts and assumptions separated. Sent to Telegram. |
| **Player risk alerts** | every day 09:00 | A digest of suspicious players in Telegram (HIGH and MEDIUM), a pseudonymized list in Google Sheets, and a log of sent alerts in the database (no repeats). |
 
The report can optionally also be sent by email (a Gmail node after `Format report`).
 
If the LLM is unavailable, the weekly report is still sent with its calculated part, and a note replaces the conclusions saying that the AI insights are unavailable.
 
## Architecture
 
```
Neon (PostgreSQL)
   |  SQL calculates metrics and rules (deterministic)
   v
n8n (Docker, local)
   |- Weekly report:  Schedule > SQL payload > Code (prompt) > Gemini > Code (report) > Telegram
   `- Alerts:         Schedule > SQL rules --+-> Code (digest) > Telegram > Code (insert) > alerts_sent
                                             `-> Code (alias only) > Google Sheets
```
 
Principles:
- **SQL counts, the LLM only explains.** All numbers come from the database. Gemini receives a finished JSON and is forbidden from inventing new metrics.
- **Thresholds in one place** (CTE `p` at the start of the SQL), so they are easy to change.
- **Deduplication:** the `alerts_sent` table; the same player with the same level is not sent again for 30 days.
- **Least privilege:** n8n runs under a dedicated role, `n8n_monitor` (read access to the required tables, write access only to `alerts_sent`). The `ground_truth` table is not accessible to it.
## Data
 
The generator `generate_synthetic.py` creates 3,000 players over 70 days (10 weeks) with a fixed seed.
 
Tables: `players` (with `device_id`, `ftd_date`), `player_game_daily`, `player_cash_daily`, the view `daily_performance`, and `ground_truth` (correct labels, used only to evaluate the rules).
 
The data deliberately includes:
- **102 real "abusers":** bonus_abuser (30), fast_withdrawal (30), multi_account (32), win_spike (10);
- **85 legitimate look-alikes** (decoys): bonus lovers, high rollers, players sharing a device, lucky winners. They check that the rules do not raise noise on normal behavior.
## Metrics (working definitions, to be approved by the metric owner)
 
- `stake` = real + bonus bets; `GGR` = stakes - wins.
- Weekly `RTP` = SUM(win) / SUM(stake). This is a weighted value, not an average of daily values.
- `bonus_share` = bonus bets / all bets.
- Active players are counted as unique players per week at player level, not as a sum over days.
- **RDC D7 (Return Deposit Count):** among players with an FTD in the week who placed real-money bets after the FTD, the share who made a second deposit within 7 days. Only "mature" FTDs are included in the cohort (at least 7 days since the FTD).
- RTP anomalies: daily deviation from the previous 8 weeks by category, |z| >= 3.
## Suspicious behavior rules
 
| Rule | Default condition |
|---|---|
| `bonus_share` | bonus bet share >= 0.75 over the window, stake volume >= 100 |
| `big_win` | net win per day >= 5000 |
| `fast_withdrawal` | withdrawal >= 80% of the deposit within 0-1 days with stakes <= 1.5x the deposit, at least 2 cycles |
| `multi_account` | 3 or more accounts on one `device_id` |
 
Level: **HIGH** if two or more rules fire, or any rule other than `big_win`; **MEDIUM** if only `big_win` fires.
 
## Evaluation results on synthetic data
 
Query `sql/15_rule_evaluation.sql`, 70-day window, compared with `ground_truth`:
 
| Metric | Value |
|---|---|
| Recall (found out of 102 real cases) | 101 (99.0%) |
| Precision of all alerts | 101 of 109 (92.7%) |
| Precision of the HIGH level | 92 of 92 (100%) |
| Precision of the MEDIUM level | 9 of 17 (52.9%) |
| False alerts on the 85 legitimate look-alikes | 0 |
 
## Limitations
 
- **The thresholds were tuned with knowledge of the generator's parameters**, so 99% recall is an upper bound. On real data the result will be worse, and the thresholds will need re-tuning.
- Synthetic "abusers" are simpler than real ones: each follows a single scenario. Real schemes combine several signals.
- `big_win` with a threshold of 5000 produces false alerts on ordinary players who have a large win, which is why it is only MEDIUM ("take a look").
- The "safe bets" rule (minimal bets on opposite outcomes) is not implemented, because it is not visible at day level.
- n8n runs locally in Docker. The schedule only fires while the container is running.
## Privacy and security
 
- Only a **pseudonym** `player_ref` is sent to Telegram and Google Sheets: the first 12 characters of SHA-256 of a secret salt and `player_id`. The salt is stored in the `ref_salt` table in the database. Reverse lookup is done by the database owner (`sql/22_lookup_player_ref.sql`).
- Pseudonymization is not anonymization: whoever has access to the database and the salt can identify a player.
- Passwords, tokens and keys are stored only in n8n credentials. They are not in the workflow JSON. Before publishing, replace `REPLACE_WITH_CHAT_ID` with a placeholder.
- Moving to a production project: first agree with security or management whether data may be sent to Telegram, Google Sheets and an LLM. For production data it is better to disable the LLM and keep only the calculated part, and to use approved corporate channels instead of public ones.
## How to run
 
1. `pip install -r requirements.txt`, copy `.env.example` to `.env` and set your `SYNTH_DATABASE_URL`.
2. `python generate_synthetic.py --write` creates the tables in a separate synthetic database (without `--write` it only writes CSV files to `out/`).
3. In the SQL Editor, run `sql/20_roles_and_alert_log.sql` (set the role password yourself) and `sql/21_player_ref_salt.sql`.
4. In n8n, create credentials: Postgres (role `n8n_monitor`, SSL Require), Telegram, Google Gemini (PaLM) API, Google Sheets (OAuth).
5. Import `n8n/workflow_weekly_health_report.json` and `n8n/workflow_player_risk_alerts.json` (paste onto an empty canvas), choose the credentials, set the chat ID, and in Google Sheets add a sheet with the headers `player_ref`, `severity`, `n_rules`, `signals`, `as_of`.
6. Run **Manual test**, then activate the workflows.
## Structure
 
```
generate_synthetic.py       synthetic data generator
sql/01-05                   weekly metrics, categories, RTP anomalies, RDC
sql/10, 12                  rule development (12 uses ground_truth)
sql/13                      production alert query
sql/14                      payload for the weekly report
sql/15                      rule evaluation against ground_truth
sql/20-22                   role, alert log, pseudonymization
n8n/                        workflows (JSON) and the scripts that build them
```
 
Claude finished the response
