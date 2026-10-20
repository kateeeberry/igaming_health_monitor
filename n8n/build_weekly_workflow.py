"""Збирає n8n/workflow_weekly_health_report.json (вставка через Cmd+V на полотні n8n)."""
import json, uuid, pathlib

root = pathlib.Path(__file__).resolve().parent.parent
sql = (root / "sql" / "14_weekly_report_payload.sql").read_text(encoding="utf-8").strip().rstrip(";")

PROMPT = r"""
const payload = JSON.parse($input.first().json.payload);
const prompt = `Ти аналітик iGaming. Нижче JSON з метриками проєкту: останній повний тиждень (cur) проти попереднього (prev).
Визначення: stake = реальні + бонусні ставки; GGR = ставки - виграші; RTP = виграші / ставки за тиждень;
bonus_share_pct = частка бонусних ставок; RDC D7 = частка гравців із FTD у тижні, що зробили другий депозит протягом 7 днів.
Дані синтетичні. Використовуй ТІЛЬКИ числа з JSON, нічого не вигадуй і не рахуй нових метрик.

Напиши звіт українською, до 1500 символів, звичайним текстом без Markdown і без HTML, у такій структурі:
1) Факти: 3-5 ключових змін (число, напрямок, % зміни).
2) Припущення (позначай явно словом «припущення» і не подавай як факт): можливі причини змін.
3) Три бізнес-висновки.
4) Рекомендації: 2-3 конкретні дії.
Якщо є аномалія RTP за днем, обов'язково згадай її в фактах. Порівняй її з top_player_day_net_wins: якщо чистий виграш одного гравця (player_ref) співмірний із від'ємним GGR дня, напиши це ФАКТОМ із числами; не вгадуй причин, яких немає в JSON.

JSON:
${JSON.stringify(payload)}`;
return [{ json: { prompt, period_end: payload.period_end, payload,
  body: { contents: [{ parts: [{ text: prompt }] }], generationConfig: { temperature: 0.2 } } } }];
""".strip()

AFTER = r"""
// Суха частина ЗАВЖДИ будується з розрахунків; текст Gemini додається, лише якщо він є.
const g = $input.first().json;
const { payload, period_end } = $('Build prompt').first().json;
const names = { ggr: 'GGR', rtp_pct: 'RTP, %', stake: 'Ставки', bets_count: 'К-сть ставок', avg_bet: 'Середня ставка',
  active_players: 'Активні гравці', bonus_share_pct: 'Частка бонусних ставок, %', ggr_margin_pct: 'GGR margin, %' };
const f = v => Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 });
const sign = v => (v > 0 ? '+' : '') + v;
let text = `Weekly health update (до ${period_end})\nТиждень проти попереднього:\n`;
text += payload.metrics.map(m => `• ${names[m.metric] || m.metric}: ${f(m.prev_value)} → ${f(m.cur_value)} (${sign(m.pct_change)}%)`).join('\n');
if (payload.rdc_d7_by_ftd_week?.length) {
  text += '\n\nRDC D7 (когорта за тижнем FTD):\n' + payload.rdc_d7_by_ftd_week
    .map(r => `• тиждень ${r.ftd_week}: ${r.rdc_d7_pct}% (когорта ${r.cohort_size})`).join('\n');
}
if (payload.rtp_daily_anomalies?.length) {
  text += '\n\nАномалії RTP (|z| від 3):\n' + payload.rtp_daily_anomalies
    .map(a => `• ${a.report_date} ${a.game_category}: RTP ${a.rtp_pct}% (z=${a.z_score})`).join('\n');
}
const ai = g.candidates?.[0]?.content?.parts?.map(p => p.text).join('')   // HTTP-вузол
        ?? g.content?.parts?.map(p => p.text).join('')                      // вузол Google Gemini
        ?? g.text;
text += ai
  ? `\n\nAI-висновки (Gemini):\n${ai}`
  : '\n\n(AI-висновки недоступні цього разу: показано лише розрахунки.)';
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
