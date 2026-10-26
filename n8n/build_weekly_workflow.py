"""Builds n8n/workflow_weekly_health_report.json (paste onto the n8n canvas with Cmd+V)."""
import json, uuid, pathlib

root = pathlib.Path(__file__).resolve().parent.parent
sql = (root / "sql" / "14_weekly_report_payload.sql").read_text(encoding="utf-8").strip().rstrip(";")

PROMPT = r"""
const payload = JSON.parse($input.first().json.payload);
const prompt = `You are an iGaming analyst. Below is a JSON with project metrics: the last full week (cur) vs the previous one (prev).
Definitions: stake = real + bonus bets; GGR = stakes - wins; RTP = wins / stakes for the week;
bonus_share_pct = share of bonus bets; RDC D7 = share of players with an FTD in the week who made a second deposit within 7 days.
The data is synthetic. Use ONLY the numbers in the JSON; do not invent anything and do not calculate new metrics.
Do not introduce player segments, labels or terms that are not in the JSON (for example, do not mention VIP players).

Write the report in English, up to 1500 characters, plain text without Markdown or HTML, in this structure:
1) Facts: 3-5 key changes (number, direction, % change).
2) Assumptions (mark them explicitly with the word "assumption" and do not present them as fact): possible causes of the changes.
3) Three business conclusions.
4) Recommendations: 2-3 concrete actions.
If there is a daily RTP anomaly, be sure to mention it in the facts. Compare it with top_player_day_net_wins: if one player's (player_ref) net win is comparable to the day's negative GGR, state this as a FACT with the numbers; do not guess causes that are not in the JSON.

JSON:
${JSON.stringify(payload)}`;
return [{ json: { prompt, period_end: payload.period_end, payload,
  body: { contents: [{ parts: [{ text: prompt }] }], generationConfig: { temperature: 0.2 } } } }];
""".strip()

AFTER = r"""
// The plain part is ALWAYS built from the calculations; the Gemini text is added only if it exists.
const g = $input.first().json;
const { payload, period_end } = $('Build prompt').first().json;
const names = { ggr: 'GGR', rtp_pct: 'RTP, %', stake: 'Total stakes', bets_count: 'Bet count', avg_bet: 'Average bet',
  active_players: 'Active players', bonus_share_pct: 'Bonus bet share, %', ggr_margin_pct: 'GGR margin, %' };
const f = v => Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 });
const sign = v => (v > 0 ? '+' : '') + v;
let text = `Weekly health update (through ${period_end})\nWeek vs previous week:\n`;
text += payload.metrics.map(m => `• ${names[m.metric] || m.metric}: ${f(m.prev_value)} → ${f(m.cur_value)} (${sign(m.pct_change)}%)`).join('\n');
if (payload.rdc_d7_by_ftd_week?.length) {
  text += '\n\nRDC D7 (cohort by first-deposit week):\n' + payload.rdc_d7_by_ftd_week
    .map(r => `• week ${r.ftd_week}: ${r.rdc_d7_pct}% (cohort size ${r.cohort_size})`).join('\n');
}
if (payload.rtp_daily_anomalies?.length) {
  text += '\n\nRTP anomalies (|z| ≥ 3):\n' + payload.rtp_daily_anomalies
    .map(a => `• ${a.report_date} ${a.game_category}: RTP ${a.rtp_pct}% (z=${a.z_score})`).join('\n');
}
const ai = g.candidates?.[0]?.content?.parts?.map(p => p.text).join('')   // HTTP node
        ?? g.content?.parts?.map(p => p.text).join('')                      // Google Gemini node
        ?? g.text;
text += ai
  ? `\n\nAI insights (Gemini):\n${ai}`
  : '\n\n(AI insights unavailable this time: calculations only.)';
return [{ json: { text: text.slice(0, 4000) } }];
""".strip()

def nid(): return str(uuid.uuid4())

nodes = [
 {"parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": "0 9 * * 1"}]}},
  "id": nid(), "name": "Schedule Mon 09:00", "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2, "position": [0, 0]},
 {"parameters": {}, "id": nid(), "name": "Manual test", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [0, 200]},
 {"parameters": {"operation": "executeQuery", "query": sql, "options": {}},
  "id": nid(), "name": "Weekly metrics", "type": "n8n-nodes-base.postgres", "typeVersion": 2.5, "position": [260, 100]},
 {"parameters": {"jsCode": PROMPT}, "id": nid(), "name": "Build prompt", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [520, 100]},
 {"parameters": {"method": "POST",
   "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
   "authentication": "predefinedCredentialType", "nodeCredentialType": "googlePalmApi",
   "sendBody": True, "specifyBody": "json", "jsonBody": "={{ JSON.stringify($json.body) }}", "options": {}},
  "id": nid(), "name": "Gemini summary", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [780, 100],
  "onError": "continueRegularOutput"},
 {"parameters": {"jsCode": AFTER}, "id": nid(), "name": "Format report", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1040, 100]},
 {"parameters": {"resource": "message", "operation": "sendMessage", "chatId": "REPLACE_WITH_CHAT_ID",
   "text": "={{ $json.text }}", "additionalFields": {"appendAttribution": False, "parse_mode": "HTML"}},
  "id": nid(), "name": "Send to Telegram", "type": "n8n-nodes-base.telegram", "typeVersion": 1.2, "position": [1300, 100]},
]
chain = [("Schedule Mon 09:00","Weekly metrics"),("Manual test","Weekly metrics"),("Weekly metrics","Build prompt"),
         ("Build prompt","Gemini summary"),("Gemini summary","Format report"),("Format report","Send to Telegram")]
conn = {}
for a,b in chain:
    conn.setdefault(a, {"main": [[]]})["main"][0].append({"node": b, "type": "main", "index": 0})
wf = {"name": "Weekly health report", "nodes": nodes, "connections": conn, "active": False,
      "settings": {"executionOrder": "v1"}, "pinData": {}}
out = root / "n8n" / "workflow_weekly_health_report.json"
out.write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")
print("written", out)
