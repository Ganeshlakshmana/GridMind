import { useState, useEffect, useRef, useCallback } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Area, AreaChart } from "recharts";

const API = "http://localhost:8080";

// ── Design tokens ──────────────────────────────────────────────────────────
const css = `
  @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap');

  * { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:        #060b18;
    --bg2:       #0d1526;
    --bg3:       #111d35;
    --border:    #1e2d4a;
    --border2:   #243558;
    --teal:      #00d4aa;
    --teal-dim:  #00d4aa22;
    --teal-glow: #00d4aa44;
    --amber:     #f59e0b;
    --red:       #ef4444;
    --blue:      #3b82f6;
    --text:      #e2e8f0;
    --text2:     #94a3b8;
    --text3:     #475569;
    --mono:      'Space Mono', monospace;
    --sans:      'DM Sans', sans-serif;
  }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    height: 100vh;
    overflow: hidden;
  }

  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-track { background: var(--bg2); }
  ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 2px; }

  @keyframes pulse-ring {
    0% { transform: scale(1); opacity: 1; }
    100% { transform: scale(2.5); opacity: 0; }
  }
  @keyframes fadeSlideIn {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes shimmer {
    0%   { background-position: -200% 0; }
    100% { background-position:  200% 0; }
  }
  @keyframes blink {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0; }
  }
  @keyframes slideRight {
    from { transform: translateX(-100%); opacity: 0; }
    to   { transform: translateX(0);     opacity: 1; }
  }
  @keyframes countUp {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  .fade-in { animation: fadeSlideIn 0.3s ease forwards; }

  .skeleton {
    background: linear-gradient(90deg, var(--bg3) 25%, var(--border) 50%, var(--bg3) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: 4px;
  }
`;

// ── Status config ──────────────────────────────────────────────────────────
const STATUS = {
  healthy: { color: "#00d4aa", label: "Healthy", pulse: false },
  degraded: { color: "#f59e0b", label: "Degraded", pulse: true },
  offline: { color: "#ef4444", label: "Offline", pulse: true },
  warning: { color: "#3b82f6", label: "Warning", pulse: true },
};

const ANOMALY_LABELS = {
  low_output: "Low Output",
  offline: "Offline",
  battery_drain: "Battery Drain",
  inverter_fault: "Inverter Fault",
};

// ── Components ─────────────────────────────────────────────────────────────

function StatusDot({ status, size = 8 }) {
  const cfg = STATUS[status] || STATUS.healthy;
  return (
    <span style={{ position: "relative", display: "inline-flex", alignItems: "center", justifyContent: "center", width: size * 3, height: size * 3 }}>
      {cfg.pulse && (
        <span style={{
          position: "absolute",
          width: size, height: size,
          borderRadius: "50%",
          background: cfg.color,
          opacity: 0.4,
          animation: "pulse-ring 1.5s ease-out infinite",
        }} />
      )}
      <span style={{
        width: size, height: size,
        borderRadius: "50%",
        background: cfg.color,
        boxShadow: `0 0 ${size}px ${cfg.color}66`,
        display: "block",
        position: "relative",
        zIndex: 1,
      }} />
    </span>
  );
}

function KpiCard({ label, value, sub, color = "var(--teal)", loading }) {
  return (
    <div style={{
      background: "var(--bg2)",
      border: "1px solid var(--border)",
      borderRadius: 12,
      padding: "18px 22px",
      flex: 1,
      position: "relative",
      overflow: "hidden",
      transition: "border-color 0.2s",
    }}
      onMouseEnter={e => e.currentTarget.style.borderColor = color + "66"}
      onMouseLeave={e => e.currentTarget.style.borderColor = "var(--border)"}
    >
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: `linear-gradient(90deg, transparent, ${color}, transparent)` }} />
      <div style={{ fontSize: 11, fontFamily: "var(--mono)", color: "var(--text3)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 8 }}>{label}</div>
      {loading ? (
        <div className="skeleton" style={{ height: 32, width: "60%", marginBottom: 6 }} />
      ) : (
        <div style={{ fontSize: 28, fontFamily: "var(--mono)", fontWeight: 700, color, animation: "countUp 0.4s ease", lineHeight: 1 }}>{value}</div>
      )}
      <div style={{ fontSize: 12, color: "var(--text3)", marginTop: 6, fontFamily: "var(--mono)" }}>{sub}</div>
    </div>
  );
}

function SparkLine({ data, color = "#00d4aa" }) {
  if (!data || data.length < 2) return null;
  const points = data.map((d, i) => ({ i, v: d.solar_output_kw ?? 0 }));
  return (
    <ResponsiveContainer width="100%" height={48}>
      <AreaChart data={points} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.3} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} fill="url(#sg)" dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function SystemDrawer({ system, onClose }) {
  if (!system) return null;
  const cfg = STATUS[system.status] || STATUS.healthy;
  const history = system.history || [];
  const chartData = history.slice(-12).map((r, i) => ({
    h: i,
    out: r.solar_output_kw ?? 0,
    exp: r.expected_output_kw ?? 0,
    soc: r.battery_soc_pct ?? null,
  }));

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 50,
      display: "flex", alignItems: "flex-end", justifyContent: "center",
      background: "#00000088",
    }} onClick={onClose}>
      <div style={{
        background: "var(--bg2)",
        border: "1px solid var(--border2)",
        borderRadius: "16px 16px 0 0",
        width: "100%", maxWidth: 720,
        padding: "28px 32px",
        animation: "fadeSlideIn 0.25s ease",
        maxHeight: "70vh",
        overflowY: "auto",
      }} onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
              <StatusDot status={system.status} size={10} />
              <span style={{ fontFamily: "var(--mono)", fontSize: 18, fontWeight: 700, color: cfg.color }}>{system.system_id}</span>
              <span style={{ fontSize: 12, color: "var(--text3)", background: "var(--bg3)", padding: "2px 8px", borderRadius: 4, fontFamily: "var(--mono)" }}>{system.system_type}</span>
            </div>
            <div style={{ fontSize: 13, color: "var(--text2)" }}>{system.location} · {cfg.label}</div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "1px solid var(--border)", color: "var(--text3)", borderRadius: 8, padding: "4px 12px", cursor: "pointer", fontSize: 13 }}>✕ Close</button>
        </div>

        {/* Metrics grid */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 24 }}>
          {[
            { label: "Output", value: `${system.solar_output_kw}`, unit: "kW" },
            { label: "Expected", value: `${system.expected_output_kw}`, unit: "kW" },
            { label: "Feed-in", value: `${system.grid_feed_in_kw}`, unit: "kW" },
            { label: "Capacity", value: `${system.solar_capacity_kw}`, unit: "kW" },
          ].map(m => (
            <div key={m.label} style={{ background: "var(--bg3)", borderRadius: 8, padding: "12px 14px" }}>
              <div style={{ fontSize: 10, color: "var(--text3)", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>{m.label}</div>
              <div style={{ fontFamily: "var(--mono)", fontSize: 16, fontWeight: 700, color: "var(--text)" }}>
                {m.value} <span style={{ fontSize: 11, color: "var(--text3)" }}>{m.unit}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Battery SOC */}
        {system.battery_soc_pct !== null && system.battery_soc_pct !== undefined && (
          <div style={{ marginBottom: 24 }}>
            <div style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>Battery SOC</div>
            <div style={{ background: "var(--bg3)", borderRadius: 6, height: 8, overflow: "hidden" }}>
              <div style={{
                height: "100%",
                width: `${system.battery_soc_pct}%`,
                background: system.battery_soc_pct < 20 ? "var(--red)" : system.battery_soc_pct < 40 ? "var(--amber)" : "var(--teal)",
                borderRadius: 6,
                transition: "width 0.6s ease",
              }} />
            </div>
            <div style={{ fontSize: 12, color: "var(--text2)", marginTop: 4, fontFamily: "var(--mono)" }}>{system.battery_soc_pct}%</div>
          </div>
        )}

        {/* 12h chart */}
        {chartData.length > 1 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>Last 12h Output</div>
            <ResponsiveContainer width="100%" height={80}>
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="og" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00d4aa" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#00d4aa" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="h" hide />
                <YAxis hide />
                <Tooltip
                  contentStyle={{ background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 11, fontFamily: "var(--mono)" }}
                  labelStyle={{ color: "var(--text3)" }}
                />
                <Area type="monotone" dataKey="out" stroke="#00d4aa" strokeWidth={2} fill="url(#og)" dot={false} name="Output" />
                <Line type="monotone" dataKey="exp" stroke="#475569" strokeWidth={1} dot={false} strokeDasharray="3 3" name="Expected" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Alerts */}
        {system.alerts && system.alerts.length > 0 && (
          <div>
            <div style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>Alerts</div>
            {system.alerts.map((a, i) => (
              <div key={i} style={{ fontSize: 12, color: "var(--amber)", background: "#f59e0b11", border: "1px solid #f59e0b22", borderRadius: 6, padding: "8px 12px", marginBottom: 6, fontFamily: "var(--mono)" }}>{a}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ChatMessage({ msg }) {
  const isUser = msg.role === "user";
  const isSystem = msg.role === "system";

  if (isSystem) {
    return (
      <div style={{ textAlign: "center", padding: "8px 0" }}>
        <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--mono)", background: "var(--bg3)", padding: "3px 10px", borderRadius: 12 }}>{msg.content}</span>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", gap: 10, justifyContent: isUser ? "flex-end" : "flex-start", animation: "fadeSlideIn 0.25s ease" }}>
      {!isUser && (
        <div style={{
          width: 28, height: 28, borderRadius: "50%", flexShrink: 0,
          background: "linear-gradient(135deg, #00d4aa, #0ea5e9)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 12, fontWeight: 700, color: "#000", fontFamily: "var(--mono)",
          boxShadow: "0 0 12px #00d4aa44",
        }}>G</div>
      )}
      <div style={{
        maxWidth: "80%",
        background: isUser ? "linear-gradient(135deg, #00d4aa22, #0ea5e922)" : "var(--bg3)",
        border: `1px solid ${isUser ? "#00d4aa33" : "var(--border)"}`,
        borderRadius: isUser ? "16px 4px 16px 16px" : "4px 16px 16px 16px",
        padding: "10px 14px",
        fontSize: 13,
        lineHeight: 1.6,
        color: "var(--text)",
      }}>
        {typeof msg.content === "string" ? (
          <div style={{ whiteSpace: "pre-wrap", fontFamily: msg.role === "agent" ? "var(--sans)" : "var(--sans)" }}>{msg.content}</div>
        ) : msg.content}
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
      <div style={{ width: 28, height: 28, borderRadius: "50%", background: "linear-gradient(135deg, #00d4aa, #0ea5e9)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, color: "#000", fontFamily: "var(--mono)" }}>G</div>
      <div style={{ background: "var(--bg3)", border: "1px solid var(--border)", borderRadius: "4px 16px 16px 16px", padding: "12px 16px", display: "flex", gap: 5 }}>
        {[0, 1, 2].map(i => (
          <div key={i} style={{
            width: 6, height: 6, borderRadius: "50%", background: "var(--teal)",
            animation: "blink 1.2s ease infinite",
            animationDelay: `${i * 0.2}s`,
          }} />
        ))}
      </div>
    </div>
  );
}


function FleetSummaryCard({ data }) {
  if (!data) return null;
  const by = data.by_status || {};
  const STATUS_COLOR = { healthy: "#00d4aa", degraded: "#f59e0b", offline: "#ef4444", warning: "#3b82f6" };
  return (
    <div style={{ fontSize: 12, fontFamily: "var(--mono)" }}>
      <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 16px", marginBottom: 8 }}>
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          {Object.entries(by).map(([status, count]) => (
            <div key={status} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: STATUS_COLOR[status] || "var(--text)" }}>{count}</div>
              <div style={{ fontSize: 10, color: "var(--text3)", textTransform: "uppercase" }}>{status}</div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)", display: "flex", gap: 16, fontSize: 11, color: "var(--text2)" }}>
          <span>⚡ {data.total_output_kw} kW</span>
          <span>📊 avg {data.avg_output_kw} kW/system</span>
          <span>🔌 {data.total_feed_in_kw} kW feed-in</span>
        </div>
      </div>
      {data.systems_needing_attention?.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--amber)", fontFamily: "var(--sans)" }}>
          ⚠ {data.systems_needing_attention.length} system{data.systems_needing_attention.length !== 1 ? "s" : ""} need attention: {data.systems_needing_attention.slice(0, 3).map(s => s.system_id).join(", ")}{data.systems_needing_attention.length > 3 ? ` +${data.systems_needing_attention.length - 3} more` : ""}
        </div>
      )}
    </div>
  );
}

function AnomalyListCard({ data, onSystemClick }) {
  if (!data?.anomalies?.length) return null;
  const STATUS_COLOR = { healthy: "#00d4aa", degraded: "#f59e0b", offline: "#ef4444", warning: "#3b82f6" };
  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 16px", fontSize: 12 }}>
      {data.anomalies.map((a, i) => (
        <div key={i} onClick={() => onSystemClick(a.system_id)}
          style={{
            display: "flex", gap: 10, alignItems: "center", padding: "7px 0",
            borderBottom: i < data.anomalies.length - 1 ? "1px solid var(--border)" : "none",
            cursor: "pointer"
          }}
          onMouseEnter={e => e.currentTarget.style.opacity = "0.7"}
          onMouseLeave={e => e.currentTarget.style.opacity = "1"}
        >
          <StatusDot status={a.status} size={7} />
          <span style={{ fontFamily: "var(--mono)", fontWeight: 700, color: "var(--text)", minWidth: 70 }}>{a.system_id}</span>
          <span style={{ color: STATUS_COLOR[a.status] || "var(--text2)", minWidth: 80, fontSize: 11 }}>{a.anomaly_type?.replace(/_/g, " ") || a.status}</span>
          <span style={{ color: "var(--text3)", fontSize: 11 }}>{a.location}</span>
          <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 11, color: "var(--text2)" }}>{a.solar_output_kw} kW</span>
        </div>
      ))}
    </div>
  );
}

function SystemCard({ data }) {
  if (!data) return null;
  const cfg = { healthy: "#00d4aa", degraded: "#f59e0b", offline: "#ef4444", warning: "#3b82f6" };
  const color = cfg[data.status] || "var(--text)";
  const history = data.history || [];
  const chartData = history.slice(-12).map((r, i) => ({ h: i, out: r.solar_output_kw ?? 0, exp: r.expected_output_kw ?? 0 }));
  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 16px", fontSize: 12 }}>
      <div style={{ display: "flex", gap: 16, marginBottom: 12, flexWrap: "wrap" }}>
        {[
          { label: "Output", value: `${data.solar_output_kw} kW` },
          { label: "Expected", value: `${data.expected_output_kw} kW` },
          { label: "Capacity", value: `${data.solar_capacity_kw} kW` },
          data.battery_soc_pct != null ? { label: "Battery", value: `${data.battery_soc_pct}%` } : null,
        ].filter(Boolean).map(m => (
          <div key={m.label}>
            <div style={{ fontSize: 10, color: "var(--text3)", textTransform: "uppercase", marginBottom: 2 }}>{m.label}</div>
            <div style={{ fontFamily: "var(--mono)", fontWeight: 700, color: "var(--text)" }}>{m.value}</div>
          </div>
        ))}
      </div>
      {chartData.length > 2 && (
        <ResponsiveContainer width="100%" height={60}>
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="cg" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={color} stopOpacity={0.3} />
                <stop offset="95%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <Area type="monotone" dataKey="out" stroke={color} strokeWidth={2} fill="url(#cg)" dot={false} />
            <Line type="monotone" dataKey="exp" stroke="#475569" strokeWidth={1} dot={false} strokeDasharray="3 3" />
          </AreaChart>
        </ResponsiveContainer>
      )}
      {data.alerts?.length > 0 && (
        <div style={{ marginTop: 10, fontSize: 11, color: "var(--amber)" }}>
          {data.alerts[data.alerts.length - 1]}
        </div>
      )}
    </div>
  );
}

function TrendsCard({ data, metric }) {
  if (!data?.series) return null;
  const label = metric?.replace(/_/g, " ") || "output";
  const chartData = data.series.map(p => ({ h: p.hour_index, v: p.avg }));
  const summary = data.summary || {};
  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 16px", fontSize: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
        <span style={{ fontSize: 10, color: "var(--text3)", textTransform: "uppercase", fontFamily: "var(--mono)" }}>{label} · 24h</span>
        <span style={{ fontSize: 11, color: summary.overall_trend === "improving" ? "var(--teal)" : summary.overall_trend === "declining" ? "var(--red)" : "var(--text2)", fontFamily: "var(--mono)" }}>
          {summary.overall_trend}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={70}>
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id="tg" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#0ea5e9" stopOpacity={0.4} />
              <stop offset="95%" stopColor="#0ea5e9" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="h" hide />
          <YAxis hide />
          <Tooltip contentStyle={{ background: "var(--bg3)", border: "1px solid var(--border)", fontSize: 11, fontFamily: "var(--mono)" }} />
          <Area type="monotone" dataKey="v" stroke="#0ea5e9" strokeWidth={2} fill="url(#tg)" dot={false} name={label} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function EscalationsCard({ data }) {
  if (!data?.length) return (
    <div style={{ fontSize: 12, color: "var(--teal)", fontFamily: "var(--mono)" }}>✓ No open escalation tickets.</div>
  );
  const SEV_COLOR = { critical: "#ef4444", high: "#f59e0b", medium: "#3b82f6", low: "#94a3b8" };
  return (
    <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 16px", fontSize: 12 }}>
      {data.map((t, i) => (
        <div key={i} style={{
          display: "flex", gap: 10, alignItems: "flex-start", padding: "7px 0",
          borderBottom: i < data.length - 1 ? "1px solid var(--border)" : "none"
        }}>
          <span style={{
            fontFamily: "var(--mono)", fontWeight: 700, color: SEV_COLOR[t.severity] || "var(--text2)",
            fontSize: 10, padding: "2px 6px", borderRadius: 4, background: (SEV_COLOR[t.severity] || "#94a3b8") + "22",
            whiteSpace: "nowrap", marginTop: 1
          }}>{t.severity?.toUpperCase()}</span>
          <div>
            <div style={{ fontFamily: "var(--mono)", color: "var(--text)", marginBottom: 2 }}>{t.system_id} · {t.ticket_id}</div>
            <div style={{ color: "var(--text2)", fontSize: 11, fontFamily: "var(--sans)" }}>{t.reason}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function ReportCard({ report }) {
  if (!report) return null;
  const ex = report.executive_summary || {};
  const session = report.session || {};
  const actions = session.actions_taken || [];
  const verified = session.verification || [];

  return (
    <div style={{ fontSize: 12, fontFamily: "var(--mono)" }}>
      {/* Health bar */}
      <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 16px", marginBottom: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
          <span style={{ color: "var(--text3)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em" }}>Fleet Health After</span>
          <span style={{ color: "var(--teal)", fontWeight: 700 }}>{ex.health_score_pct}%</span>
        </div>
        <div style={{ background: "var(--bg3)", borderRadius: 4, height: 6 }}>
          <div style={{ height: "100%", width: `${ex.health_score_pct}%`, background: "linear-gradient(90deg, #00d4aa, #0ea5e9)", borderRadius: 4, transition: "width 1s ease" }} />
        </div>
        <div style={{ display: "flex", gap: 16, marginTop: 10, color: "var(--text2)", fontSize: 11 }}>
          <span>⚡ {ex.total_output_kw} kW</span>
          <span>⚠ {ex.anomaly_count} anomalies</span>
          <span>📋 {ex.open_escalations} escalations</span>
        </div>
      </div>

      {/* Triage rationale */}
      {session.triage_plan?.rationale && (
        <div style={{ background: "#00d4aa0a", border: "1px solid #00d4aa22", borderRadius: 10, padding: "12px 14px", marginBottom: 10, fontSize: 11, color: "var(--text2)", lineHeight: 1.6, fontFamily: "var(--sans)" }}>
          {session.triage_plan.rationale}
        </div>
      )}

      {/* Actions */}
      {actions.length > 0 && (
        <div style={{ background: "var(--bg2)", border: "1px solid var(--border)", borderRadius: 10, padding: "14px 16px", marginBottom: 10 }}>
          <div style={{ fontSize: 10, color: "var(--text3)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>Actions Taken</div>
          {actions.slice(0, 6).map((a, i) => {
            const isResolve = a.type === "resolve";
            const ok = a.success || a.status === "open";
            return (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
                <span style={{ color: isResolve ? "var(--teal)" : "var(--amber)" }}>{isResolve ? "✓" : "↑"}</span>
                <span style={{ color: "var(--text)", fontWeight: 600 }}>{a.system_id}</span>
                <span style={{ color: "var(--text3)" }}>·</span>
                <span style={{ color: "var(--text2)" }}>{a.action || `escalate (${a.severity})`}</span>
                {!ok && <span style={{ color: "var(--red)", fontSize: 10 }}>FAILED</span>}
              </div>
            );
          })}
          {actions.length > 6 && <div style={{ color: "var(--text3)", fontSize: 11 }}>+{actions.length - 6} more</div>}
        </div>
      )}

      {/* Verification */}
      {verified.length > 0 && (
        <div style={{ fontSize: 11, color: "var(--text2)" }}>
          ✅ {verified.filter(v => v.fix_succeeded).length}/{verified.length} fixes verified healthy
        </div>
      )}
    </div>
  );
}

// ── Main App ───────────────────────────────────────────────────────────────

export default function App() {
  const [fleet, setFleet] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([
    { role: "system", content: "GridMind Agent · Connected to 50 systems" },
  ]);
  const [input, setInput] = useState("");
  const [agentRunning, setAgentRunning] = useState(false);
  const [sortBy, setSortBy] = useState("system_id");
  const [sortDir, setSortDir] = useState("asc");
  const chatEndRef = useRef(null);

  const fetchFleet = useCallback(async () => {
    try {
      const [f, s] = await Promise.all([
        fetch(`${API}/fleet`).then(r => r.json()),
        fetch(`${API}/fleet/summary`).then(r => r.json()),
      ]);
      setFleet(f);
      setSummary(s);
    } catch (e) {
      console.error("Fleet fetch failed", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchFleet(); }, [fetchFleet]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, agentRunning]);

  const sendMessage = async (prompt) => {
    if (!prompt.trim() || agentRunning) return;
    setInput("");
    setMessages(m => [...m, { role: "user", content: prompt }]);
    setAgentRunning(true);

    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      const resp = await res.json();

      switch (resp.type) {
        case "refusal":
          setMessages(m => [...m, { role: "agent", content: `🚫 ${resp.message}` }]);
          break;

        case "error":
          setMessages(m => [...m, { role: "agent", content: `⚠ ${resp.message}` }]);
          break;

        case "fleet_summary":
          setMessages(m => [...m,
          { role: "agent", content: resp.message },
          { role: "agent", content: <FleetSummaryCard data={resp.data} /> },
          ]);
          break;

        case "anomalies":
          setMessages(m => [...m,
          { role: "agent", content: resp.message },
          { role: "agent", content: <AnomalyListCard data={resp.data} onSystemClick={(sid) => sendMessage(`Tell me about ${sid}`)} /> },
          ]);
          break;

        case "system":
          setMessages(m => [...m,
          { role: "agent", content: resp.message },
          { role: "agent", content: <SystemCard data={resp.data} /> },
          ]);
          break;

        case "trends":
          setMessages(m => [...m,
          { role: "agent", content: resp.message },
          { role: "agent", content: <TrendsCard data={resp.data} metric={resp.metric} /> },
          ]);
          break;

        case "escalations":
          setMessages(m => [...m,
          { role: "agent", content: resp.message },
          { role: "agent", content: <EscalationsCard data={resp.data} /> },
          ]);
          break;

        case "agent_report":
          const report = resp.data;
          const ex = report.executive_summary || {};
          const summary_text = ex.health_score_pct !== undefined
            ? `Fleet health is now **${ex.health_score_pct}%** — ${ex.anomaly_count} anomalies remain, ${ex.open_escalations} escalations open.`
            : "Session complete.";
          setMessages(m => [...m,
          { role: "agent", content: summary_text },
          { role: "agent", content: <ReportCard report={report} /> },
          ]);
          fetchFleet();
          break;

        default:
          setMessages(m => [...m, { role: "agent", content: JSON.stringify(resp) }]);
      }
    } catch (e) {
      setMessages(m => [...m, { role: "agent", content: `⚠ Error: ${e.message}` }]);
    } finally {
      setAgentRunning(false);
    }
  };

  const handleSystemClick = (sys) => {
    setSelected(sys);
  };

  const handleSystemChat = (sys) => {
    setSelected(null);
    sendMessage(`Tell me about ${sys.system_id} in ${sys.location}. Current status: ${sys.status}.`);
  };

  // Fleet filtering + sorting
  const filteredFleet = fleet
    .filter(s => filter === "all" || s.status === filter)
    .sort((a, b) => {
      let va = a[sortBy], vb = b[sortBy];
      if (typeof va === "string") va = va.toLowerCase(), vb = vb.toLowerCase();
      if (va === null || va === undefined) va = -Infinity;
      if (vb === null || vb === undefined) vb = -Infinity;
      return sortDir === "asc" ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
    });

  const toggleSort = (col) => {
    if (sortBy === col) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortBy(col); setSortDir("asc"); }
  };

  const statusCounts = fleet.reduce((acc, s) => {
    acc[s.status] = (acc[s.status] || 0) + 1;
    return acc;
  }, {});

  const PRESETS = [
    "Run full diagnostic",
    "Fix all issues automatically",
    "Show offline systems",
    "What needs attention today?",
  ];

  const ColHeader = ({ col, label }) => (
    <th onClick={() => toggleSort(col)} style={{
      padding: "8px 12px", textAlign: "left", fontSize: 10,
      color: sortBy === col ? "var(--teal)" : "var(--text3)",
      fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.06em",
      cursor: "pointer", userSelect: "none", whiteSpace: "nowrap",
      background: "var(--bg2)", position: "sticky", top: 0, zIndex: 1,
      borderBottom: "1px solid var(--border)",
    }}>
      {label} {sortBy === col ? (sortDir === "asc" ? "↑" : "↓") : ""}
    </th>
  );

  return (
    <>
      <style>{css}</style>

      {/* ── Top bar ─────────────────────────────────────────────── */}
      <div style={{
        height: 48, background: "var(--bg2)", borderBottom: "1px solid var(--border)",
        display: "flex", alignItems: "center", padding: "0 24px",
        justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 8,
            background: "linear-gradient(135deg, #00d4aa, #0ea5e9)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 13, fontWeight: 700, color: "#000", fontFamily: "var(--mono)",
            boxShadow: "0 0 16px #00d4aa44",
          }}>G</div>
          <span style={{ fontFamily: "var(--mono)", fontWeight: 700, fontSize: 14, letterSpacing: "0.04em" }}>GRIDMIND</span>
          <span style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--mono)" }}>VPP Operations · Berlin</span>
        </div>
        <div style={{ display: "flex", gap: 16, fontSize: 12, fontFamily: "var(--mono)", color: "var(--text3)" }}>
          {Object.entries(statusCounts).map(([status, count]) => (
            <span key={status} style={{ color: STATUS[status]?.color || "var(--text3)" }}>
              {count} {status}
            </span>
          ))}
          <span style={{ color: "var(--text3)" }}>|</span>
          <span style={{ color: loading ? "var(--amber)" : "var(--teal)" }}>
            {loading ? "connecting..." : "● live"}
          </span>
        </div>
      </div>

      {/* ── Main layout ─────────────────────────────────────────── */}
      <div style={{ display: "flex", height: "calc(100vh - 48px)" }}>

        {/* ── LEFT: Fleet panel ──────────────────────────────────── */}
        <div style={{ flex: "0 0 60%", display: "flex", flexDirection: "column", borderRight: "1px solid var(--border)", overflow: "hidden" }}>

          {/* KPI row */}
          <div style={{ padding: "16px 20px 0", display: "flex", gap: 12 }}>
            <KpiCard
              label="Fleet Health"
              value={loading ? "—" : `${summary?.by_status?.healthy ?? 0}`}
              sub={loading ? "" : `${Math.round((summary?.by_status?.healthy ?? 0) / 50 * 100)}% of 50 systems`}
              color="var(--teal)"
              loading={loading}
            />
            <KpiCard
              label="Total Output"
              value={loading ? "—" : `${summary?.total_output_kw ?? 0}`}
              sub="kW across fleet"
              color="#0ea5e9"
              loading={loading}
            />
            <KpiCard
              label="Anomalies"
              value={loading ? "—" : `${(summary?.systems_needing_attention ?? []).length}`}
              sub="systems need attention"
              color={(summary?.systems_needing_attention ?? []).length > 0 ? "var(--amber)" : "var(--teal)"}
              loading={loading}
            />
          </div>

          {/* Filter tabs */}
          <div style={{ padding: "14px 20px 0", display: "flex", gap: 6 }}>
            {["all", "healthy", "degraded", "offline", "warning"].map(f => (
              <button key={f} onClick={() => setFilter(f)} style={{
                padding: "5px 12px", borderRadius: 20, fontSize: 11,
                fontFamily: "var(--mono)", textTransform: "capitalize",
                cursor: "pointer", transition: "all 0.15s",
                background: filter === f ? (STATUS[f]?.color || "var(--teal)") + "22" : "transparent",
                border: `1px solid ${filter === f ? (STATUS[f]?.color || "var(--teal)") + "66" : "var(--border)"}`,
                color: filter === f ? (STATUS[f]?.color || "var(--teal)") : "var(--text3)",
              }}>
                {f === "all" ? `All (${fleet.length})` : `${f} (${statusCounts[f] || 0})`}
              </button>
            ))}
          </div>

          {/* Fleet table */}
          <div style={{ flex: 1, overflow: "auto", margin: "12px 20px 16px" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <ColHeader col="system_id" label="System" />
                  <ColHeader col="status" label="Status" />
                  <ColHeader col="location" label="Location" />
                  <ColHeader col="solar_output_kw" label="Output" />
                  <ColHeader col="battery_soc_pct" label="SOC" />
                  <th style={{ padding: "8px 12px", background: "var(--bg2)", borderBottom: "1px solid var(--border)", position: "sticky", top: 0, zIndex: 1 }} />
                </tr>
              </thead>
              <tbody>
                {loading ? Array.from({ length: 10 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 6 }).map((_, j) => (
                      <td key={j} style={{ padding: "10px 12px" }}>
                        <div className="skeleton" style={{ height: 14, width: j === 0 ? 60 : j === 5 ? 40 : "80%" }} />
                      </td>
                    ))}
                  </tr>
                )) : filteredFleet.map(sys => {
                  const cfg = STATUS[sys.status] || STATUS.healthy;
                  const eff = sys.expected_output_kw > 0
                    ? Math.round(sys.solar_output_kw / sys.expected_output_kw * 100)
                    : 0;
                  return (
                    <tr key={sys.system_id}
                      onClick={() => handleSystemClick(sys)}
                      style={{
                        cursor: "pointer",
                        borderBottom: "1px solid var(--border)",
                        transition: "background 0.1s",
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = "var(--bg3)"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                    >
                      <td style={{ padding: "10px 12px", fontFamily: "var(--mono)", fontSize: 12, fontWeight: 700, color: "var(--text)" }}>{sys.system_id}</td>
                      <td style={{ padding: "10px 12px" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <StatusDot status={sys.status} size={7} />
                          <span style={{ fontSize: 11, fontFamily: "var(--mono)", color: cfg.color }}>{cfg.label}</span>
                        </div>
                      </td>
                      <td style={{ padding: "10px 12px", fontSize: 12, color: "var(--text2)" }}>{sys.location}</td>
                      <td style={{ padding: "10px 12px" }}>
                        <div style={{ fontSize: 12, fontFamily: "var(--mono)", color: "var(--text)" }}>{sys.solar_output_kw} <span style={{ fontSize: 10, color: "var(--text3)" }}>kW</span></div>
                        <div style={{ marginTop: 3, background: "var(--bg3)", borderRadius: 2, height: 3, width: 60, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${Math.min(eff, 100)}%`, background: eff < 50 ? "var(--red)" : eff < 80 ? "var(--amber)" : "var(--teal)" }} />
                        </div>
                      </td>
                      <td style={{ padding: "10px 12px" }}>
                        {sys.battery_soc_pct !== null && sys.battery_soc_pct !== undefined ? (
                          <span style={{ fontSize: 11, fontFamily: "var(--mono)", color: sys.battery_soc_pct < 20 ? "var(--red)" : "var(--text2)" }}>{sys.battery_soc_pct}%</span>
                        ) : (
                          <span style={{ fontSize: 11, color: "var(--text3)" }}>—</span>
                        )}
                      </td>
                      <td style={{ padding: "10px 12px" }}>
                        <div style={{ width: 60, height: 24 }}>
                          <SparkLine data={sys.history?.slice(-8)} color={cfg.color} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── RIGHT: Agent chat ──────────────────────────────────── */}
        <div style={{ flex: "0 0 40%", display: "flex", flexDirection: "column", background: "var(--bg)" }}>

          {/* Chat header */}
          <div style={{
            padding: "16px 20px",
            borderBottom: "1px solid var(--border)",
            display: "flex", alignItems: "center", gap: 10,
          }}>
            <div style={{
              width: 32, height: 32, borderRadius: "50%",
              background: "linear-gradient(135deg, #00d4aa, #0ea5e9)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 14, fontWeight: 700, color: "#000", fontFamily: "var(--mono)",
              boxShadow: "0 0 16px #00d4aa33",
            }}>G</div>
            <div>
              <div style={{ fontFamily: "var(--mono)", fontWeight: 700, fontSize: 13 }}>GridMind Agent</div>
              <div style={{ fontSize: 11, color: agentRunning ? "var(--amber)" : "var(--teal)", fontFamily: "var(--mono)" }}>
                {agentRunning ? "● thinking..." : "● ready"}
              </div>
            </div>
          </div>

          {/* Messages */}
          <div style={{ flex: 1, overflow: "auto", padding: "16px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
            {messages.map((msg, i) => <ChatMessage key={i} msg={msg} />)}
            {agentRunning && <TypingIndicator />}
            <div ref={chatEndRef} />
          </div>

          {/* Preset chips */}
          <div style={{ padding: "0 16px 10px", display: "flex", gap: 6, flexWrap: "wrap" }}>
            {PRESETS.map(p => (
              <button key={p} onClick={() => sendMessage(p)} disabled={agentRunning} style={{
                fontSize: 11, fontFamily: "var(--mono)",
                padding: "4px 10px", borderRadius: 12,
                background: "var(--bg3)", border: "1px solid var(--border)",
                color: "var(--text2)", cursor: agentRunning ? "not-allowed" : "pointer",
                opacity: agentRunning ? 0.5 : 1, transition: "all 0.15s",
                whiteSpace: "nowrap",
              }}
                onMouseEnter={e => !agentRunning && (e.target.style.borderColor = "var(--teal)")}
                onMouseLeave={e => (e.target.style.borderColor = "var(--border)")}
              >{p}</button>
            ))}
          </div>

          {/* Input */}
          <div style={{ padding: "0 16px 16px" }}>
            <div style={{
              display: "flex", gap: 8, alignItems: "flex-end",
              background: "var(--bg2)", border: `1px solid ${agentRunning ? "var(--amber)" : "var(--border)"}`,
              borderRadius: 12, padding: "10px 12px",
              transition: "border-color 0.2s",
            }}>
              <textarea
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(input); } }}
                placeholder="Ask GridMind anything about your fleet..."
                disabled={agentRunning}
                rows={1}
                style={{
                  flex: 1, background: "none", border: "none", outline: "none",
                  color: "var(--text)", fontSize: 13, fontFamily: "var(--sans)",
                  resize: "none", lineHeight: 1.5,
                  opacity: agentRunning ? 0.6 : 1,
                }}
              />
              <button
                onClick={() => sendMessage(input)}
                disabled={agentRunning || !input.trim()}
                style={{
                  width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                  background: agentRunning || !input.trim() ? "var(--bg3)" : "linear-gradient(135deg, #00d4aa, #0ea5e9)",
                  border: "none", cursor: agentRunning || !input.trim() ? "not-allowed" : "pointer",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  color: agentRunning || !input.trim() ? "var(--text3)" : "#000",
                  fontSize: 14, transition: "all 0.15s",
                  boxShadow: !agentRunning && input.trim() ? "0 0 12px #00d4aa44" : "none",
                }}
              >↑</button>
            </div>
            <div style={{ fontSize: 10, color: "var(--text3)", fontFamily: "var(--mono)", marginTop: 6, textAlign: "center" }}>
              Enter to send · Shift+Enter for newline · Click any system row for details
            </div>
          </div>
        </div>
      </div>

      {/* System drawer */}
      {selected && (
        <SystemDrawer
          system={selected}
          onClose={() => setSelected(null)}
          onChat={handleSystemChat}
        />
      )}
    </>
  );
}