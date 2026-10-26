"""Builds n8n/workflow_player_risk_alerts.json (import into n8n via Import from File)."""
import json, uuid, pathlib

root = pathlib.Path(__file__).resolve().parent.parent
sql = (root / "sql" / "13_alert_candidates.sql").read_text(encoding="utf-8").strip()
if sql.endswith(";"):
    sql = sql[:-1]

BUILD_DIGEST = r"""
// Build ONE digest per run so the first run (accumulated history) does not flood the chat.
const rows = $input.all().map(i => i.json);
const high = rows.filter(r => r.severity === 'HIGH');
const medium = rows.filter(r => r.severity === 'MEDIUM');
const asOf = rows[0].as_of;
const line = r => `• ${r.player_ref}: ${r.signals}`;   // only the pseudonym goes to external channels

let text = `Player risk digest (${asOf})\nHIGH: ${high.length} | MEDIUM: ${medium.length}`;
if (high.length) {
  text += `\n\nHIGH (top ${Math.min(10, high.length)}):\n` + high.slice(0, 10).map(line).join('\n');
  if (high.length > 10) text += `\n… and ${high.length - 10} more`;
}
if (medium.length) {
  text += `\n\nMEDIUM (top ${Math.min(5, medium.length)}):\n` + medium.slice(0, 5).map(line).join('\n');
  if (medium.length > 5) text += `\n… and ${medium.length - 5} more`;
}
return [{ json: { text, rows } }];
""".strip()

BUILD_INSERT = r"""
// Write to the log ONLY after a successful send (this node comes after Telegram).
const rows = $('Build digest').first().json.rows;
const esc = s => String(s).replace(/'/g, "''");
const values = rows
  .map(r => `('${esc(r.player_id)}','${esc(r.severity)}','${esc(r.signals)}')`)
  .join(',');
return [{ json: { insert_sql: `INSERT INTO alerts_sent (player_id, severity, signals) VALUES ${values}` } }];
""".strip()


SHEETS_ROWS = r"""
// For Google Sheets: ONLY the pseudonym and signals. player_id is deliberately not passed.
return $input.all().map(i => ({ json: {
  player_ref: i.json.player_ref, severity: i.json.severity,
  n_rules: i.json.n_rules, signals: i.json.signals, as_of: i.json.as_of } }));
""".strip()


def nid():
    return str(uuid.uuid4())


nodes = [
    {"parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": "0 9 * * *"}]}},
     "id": nid(), "name": "Schedule 09:00", "type": "n8n-nodes-base.scheduleTrigger",
     "typeVersion": 1.2, "position": [0, 0]},
    {"parameters": {}, "id": nid(), "name": "Manual test", "type": "n8n-nodes-base.manualTrigger",
     "typeVersion": 1, "position": [0, 200]},
    {"parameters": {"operation": "executeQuery", "query": sql, "options": {}},
     "id": nid(), "name": "Find suspicious players", "type": "n8n-nodes-base.postgres",
     "typeVersion": 2.5, "position": [260, 100]},
    {"parameters": {"jsCode": SHEETS_ROWS}, "id": nid(), "name": "Sheets rows (anonymized)",
     "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [520, 320]},
    {"parameters": {"jsCode": BUILD_DIGEST}, "id": nid(), "name": "Build digest",
     "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [520, 100]},
    {"parameters": {"resource": "message", "operation": "sendMessage", "chatId": "REPLACE_WITH_CHAT_ID",
                    "text": "={{ $json.text }}", "additionalFields": {"appendAttribution": False, "parse_mode": "HTML"}},
     "id": nid(), "name": "Send to Telegram", "type": "n8n-nodes-base.telegram",
     "typeVersion": 1.2, "position": [780, 100]},
    {"parameters": {"jsCode": BUILD_INSERT}, "id": nid(), "name": "Build insert",
     "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1040, 100]},
    {"parameters": {"operation": "executeQuery", "query": "={{ $json.insert_sql }}", "options": {}},
     "id": nid(), "name": "Save to alerts_sent", "type": "n8n-nodes-base.postgres",
     "typeVersion": 2.5, "position": [1300, 100]},
]


def link(a, b):
    return {a: {"main": [[{"node": b, "type": "main", "index": 0}]]}}


conn = {}
for a, b in [("Schedule 09:00", "Find suspicious players"), ("Manual test", "Find suspicious players"),
             ("Find suspicious players", "Build digest"), ("Build digest", "Send to Telegram"),
             ("Send to Telegram", "Build insert"), ("Build insert", "Save to alerts_sent")]:
    conn.update(link(a, b))
# second branch from Find suspicious players: rows for Sheets without player_id
conn["Find suspicious players"]["main"][0].append({"node": "Sheets rows (anonymized)", "type": "main", "index": 0})

wf = {"name": "Player risk alerts (daily)", "nodes": nodes, "connections": conn,
      "active": False, "settings": {"executionOrder": "v1"}, "pinData": {}}
out = root / "n8n" / "workflow_player_risk_alerts.json"
out.write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")
print("written", out, len(nodes), "nodes")
