'use client'

export const dynamic = 'force-dynamic'

import { useState, useEffect, useCallback } from 'react'
import { supabase } from '@/lib/supabase'
import { api, type AlertLog } from '@/lib/api'


// ---- Toast System ----
interface Toast {
  id: string
  title: string
  body?: string
  severity?: string
}

let _setToasts: React.Dispatch<React.SetStateAction<Toast[]>> | null = null

export function addToast(t: Omit<Toast, 'id'>) {
  if (_setToasts) {
    const id = Math.random().toString(36).slice(2)
    _setToasts(prev => [...prev, { ...t, id }])
    setTimeout(() => {
      _setToasts?.(prev => prev.filter(x => x.id !== id))
    }, 5000)
  }
}

function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([])
  _setToasts = setToasts

  const sevIcon: Record<string, string> = {
    critical: '🔴', high: '🟠', medium: '🟡', low: '🟢', info: '🔵'
  }

  return (
    <div className="toast-container">
      {toasts.map(t => (
        <div key={t.id} className="toast">
          <span className="toast-icon">{sevIcon[t.severity ?? 'info'] ?? '🔔'}</span>
          <div>
            <div className="toast-title">{t.title}</div>
            {t.body && <div className="toast-body">{t.body.slice(0, 120)}</div>}
          </div>
        </div>
      ))}
    </div>
  )
}

// ---- Sidebar ----
type Page = 'dashboard' | 'events' | 'alerts' | 'rules' | 'sources' | 'search'

interface SidebarProps {
  page: Page
  setPage: (p: Page) => void
  unreadCount: number
}

function Sidebar({ page, setPage, unreadCount }: SidebarProps) {
  const navItems: { id: Page; icon: string; label: string }[] = [
    { id: 'dashboard', icon: '⚡', label: 'Dashboard' },
    { id: 'events',    icon: '📡', label: 'Live Feed' },
    { id: 'alerts',    icon: '🔔', label: 'Alerts' },
    { id: 'rules',     icon: '📋', label: 'Alert Rules' },
    { id: 'sources',   icon: '🔗', label: 'Data Sources' },
    { id: 'search',    icon: '🔍', label: 'Semantic Search' },
  ]

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">⚡</div>
        <div className="sidebar-logo-text">DataPulse</div>
      </div>
      <nav style={{ flex: 1 }}>
        {navItems.map(item => (
          <button
            key={item.id}
            id={`nav-${item.id}`}
            className={`nav-item ${page === item.id ? 'active' : ''}`}
            onClick={() => setPage(item.id)}
          >
            <span style={{ fontSize: 16 }}>{item.icon}</span>
            {item.label}
            {item.id === 'alerts' && unreadCount > 0 && (
              <span className="nav-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>
            )}
          </button>
        ))}
      </nav>
      <div style={{ padding: '16px 20px', borderTop: '1px solid var(--border)' }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          <span className="live-dot" style={{ marginRight: 6 }} />
          Realtime connected
        </div>
      </div>
    </aside>
  )
}

// ---- Severity Badge ----
function SeverityBadge({ severity }: { severity?: string }) {
  if (!severity) return null
  return <span className={`badge badge-${severity}`}>{severity}</span>
}

function ModeBadge({ mode }: { mode?: string }) {
  if (!mode) return null
  const labels: Record<string, string> = { keyword: 'Keyword', semantic: 'Semantic', llm_agent: 'LLM Agent' }
  return <span className={`badge badge-${mode}`}>{labels[mode] ?? mode}</span>
}

function formatRelative(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`
  return new Date(iso).toLocaleDateString()
}

// ---- Dashboard Page ----
function DashboardPage() {
  const [stats, setStats] = useState<Awaited<ReturnType<typeof api.getStats>> | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.getStats().then(s => { setStats(s); setLoading(false) }).catch(() => setLoading(false))
    const interval = setInterval(() => api.getStats().then(setStats).catch(() => {}), 15000)
    return () => clearInterval(interval)
  }, [])

  const statCards = stats ? [
    { label: 'Documents', value: stats.documents_total, icon: '📄', color: '#6366f1' },
    { label: 'Raw Events', value: stats.events_total, icon: '📡', color: '#8b5cf6' },
    { label: 'Unread Alerts', value: stats.alerts_unread, icon: '🔔', color: '#ef4444' },
    { label: 'Active Rules', value: stats.rules_active, icon: '📋', color: '#f59e0b' },
    { label: 'Active Sources', value: stats.sources_active, icon: '🔗', color: '#10b981' },
  ] : []

  const sevColors: Record<string, string> = {
    info: '#3b82f6', low: '#10b981', medium: '#f59e0b', high: '#f97316', critical: '#ef4444'
  }

  return (
    <div>
      <div style={{ marginBottom: 28 }}>
        <h1 className="page-title">Dashboard</h1>
        <p className="page-subtitle">Real-time overview of your data ingestion pipeline</p>
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}>
          <div className="spinner" style={{ width: 36, height: 36, borderWidth: 3 }} />
        </div>
      ) : (
        <>
          <div className="stats-grid">
            {statCards.map(s => (
              <div key={s.label} className="stat-card">
                <div className="stat-icon" style={{ background: `${s.color}20` }}>
                  {s.icon}
                </div>
                <div className="stat-value">{s.value.toLocaleString()}</div>
                <div className="stat-label">{s.label}</div>
              </div>
            ))}
          </div>

          {stats && Object.keys(stats.severity_breakdown).length > 0 && (
            <div className="card">
              <div className="card-header">
                <span className="card-title">Severity Breakdown</span>
              </div>
              <div className="card-body">
                <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
                  {Object.entries(stats.severity_breakdown).map(([sev, count]) => (
                    <div key={sev} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{
                        width: 10, height: 10, borderRadius: '50%',
                        background: sevColors[sev] ?? '#6366f1'
                      }} />
                      <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{sev}</span>
                      <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
                        {count}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ---- Live Feed Page ----
function EventsPage() {
  const [docs, setDocs] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [severity, setSeverity] = useState('')
  const PAGE_SIZE = 20

  const load = useCallback(() => {
    setLoading(true)
    api.getDocuments({ page, page_size: PAGE_SIZE, severity: severity || undefined })
      .then(r => { setDocs(r.data); setTotal(r.total); setLoading(false) })
      .catch(() => setLoading(false))
  }, [page, severity])

  useEffect(() => { load() }, [load])

  // Realtime subscription for new docs
  useEffect(() => {
    const channel = supabase
      .channel('docs-feed')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'processed_documents' }, (payload: { new: Record<string, unknown> }) => {
        setDocs(prev => [payload.new as any, ...prev.slice(0, PAGE_SIZE - 1)])
        setTotal(t => t + 1)
      })
      .subscribe()
    return () => { supabase.removeChannel(channel) }
  }, [])

  const sevColors: Record<string, string> = {
    info: 'var(--sev-info)', low: 'var(--sev-low)', medium: 'var(--sev-medium)',
    high: 'var(--sev-high)', critical: 'var(--sev-critical)'
  }

  return (
    <div>
      <div className="section-header">
        <div>
          <h1 className="page-title">Live Event Feed</h1>
          <p className="page-subtitle">{total.toLocaleString()} documents ingested</p>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <span className="live-dot" />
          <select
            id="filter-severity"
            className="form-control"
            style={{ width: 'auto' }}
            value={severity}
            onChange={e => { setSeverity(e.target.value); setPage(1) }}
          >
            <option value="">All severities</option>
            {['info', 'low', 'medium', 'high', 'critical'].map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <button id="refresh-feed" className="btn btn-secondary btn-sm" onClick={load}>↻ Refresh</button>
        </div>
      </div>

      <div className="table-container">
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}>
            <div className="spinner" />
          </div>
        ) : docs.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">📡</div>
            <h3>No events yet</h3>
            <p>Start the ingestor service to begin pulling data</p>
          </div>
        ) : (
          <>
            {docs.map(doc => (
              <div key={doc.id} className="event-item" style={{ padding: '14px 20px' }}>
                <div
                  className="event-dot"
                  style={{ background: sevColors[doc.severity] ?? 'var(--sev-info)', marginTop: 4 }}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="event-title truncate">{doc.title || 'Untitled event'}</div>
                  <div className="event-meta">
                    <span>{doc.source_name}</span>
                    {doc.processed_at && <> · <span>{formatRelative(doc.processed_at)}</span></>}
                    {doc.summary && (
                      <span style={{ color: 'var(--text-muted)', marginLeft: 4 }}>
                        — {doc.summary}
                      </span>
                    )}
                  </div>
                  {doc.tags?.length > 0 && (
                    <div className="event-tags">
                      {doc.tags.slice(0, 5).map((t: string) => (
                        <span key={t} className="tag">{t}</span>
                      ))}
                    </div>
                  )}
                </div>
                <SeverityBadge severity={doc.severity} />
              </div>
            ))}
            <div className="pagination">
              <button id="page-prev" className="btn btn-secondary btn-sm" disabled={page === 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
              <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                Page {page} of {Math.ceil(total / PAGE_SIZE) || 1}
              </span>
              <button id="page-next" className="btn btn-secondary btn-sm" disabled={page >= Math.ceil(total / PAGE_SIZE)} onClick={() => setPage(p => p + 1)}>Next →</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ---- Alerts Page ----
function AlertsPage({ onRead }: { onRead: () => void }) {
  const [alerts, setAlerts] = useState<AlertLog[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [loading, setLoading] = useState(true)
  const PAGE_SIZE = 20

  const load = useCallback(() => {
    setLoading(true)
    api.getAlerts({ page, page_size: PAGE_SIZE, unread_only: unreadOnly })
      .then(r => { setAlerts(r.data); setTotal(r.total); setLoading(false) })
      .catch(() => setLoading(false))
  }, [page, unreadOnly])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    const channel = supabase
      .channel('alerts-feed')
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'alert_log' }, (payload: { new: Record<string, unknown> }) => {
        const a = payload.new as unknown as AlertLog
        setAlerts(prev => [a, ...prev.slice(0, PAGE_SIZE - 1)])
        setTotal(t => t + 1)
        onRead()
        addToast({
          title: a.alert_title ?? 'New Alert',
          body: a.alert_body ?? undefined,
          severity: a.severity ?? 'info',
        })
      })
      .subscribe()
    return () => { supabase.removeChannel(channel) }
  }, [onRead])

  const markRead = async (id: string) => {
    await api.markAlertRead(id)
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, is_read: true } : a))
    onRead()
  }

  const markAllRead = async () => {
    await api.markAllRead()
    setAlerts(prev => prev.map(a => ({ ...a, is_read: true })))
    onRead()
  }

  return (
    <div>
      <div className="section-header">
        <div>
          <h1 className="page-title">Alert Log</h1>
          <p className="page-subtitle">{total.toLocaleString()} total alerts</p>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text-secondary)', cursor: 'pointer' }}>
            <input
              id="unread-toggle"
              type="checkbox"
              checked={unreadOnly}
              onChange={e => { setUnreadOnly(e.target.checked); setPage(1) }}
              style={{ accentColor: 'var(--accent)' }}
            />
            Unread only
          </label>
          <button id="mark-all-read" className="btn btn-secondary btn-sm" onClick={markAllRead}>✓ Mark all read</button>
        </div>
      </div>

      <div className="table-container">
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}>
            <div className="spinner" />
          </div>
        ) : alerts.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">🔔</div>
            <h3>No alerts</h3>
            <p>Create alert rules to start receiving notifications</p>
          </div>
        ) : (
          <>
            {alerts.map(alert => (
              <div
                key={alert.id}
                id={`alert-${alert.id}`}
                className={`alert-item sev-${alert.severity ?? 'info'} ${!alert.is_read ? 'unread' : ''}`}
                onClick={() => !alert.is_read && markRead(alert.id)}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
                  <div className="alert-title">{alert.alert_title || 'Alert triggered'}</div>
                  <div style={{ display: 'flex', gap: 6, flexShrink: 0, alignItems: 'center' }}>
                    {!alert.is_read && (
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--accent)', display: 'inline-block' }} />
                    )}
                    <SeverityBadge severity={alert.severity ?? undefined} />
                  </div>
                </div>
                {alert.alert_body && (
                  <div className="alert-body">{alert.alert_body.slice(0, 200)}</div>
                )}
                <div className="alert-meta">
                  <span>Rule: {alert.rule_name}</span>
                  {alert.source_name && <span>· {alert.source_name}</span>}
                  <ModeBadge mode={alert.mode_used} />
                  {alert.match_score != null && (
                    <span>Score: {(alert.match_score * 100).toFixed(1)}%</span>
                  )}
                  <span>{formatRelative(alert.delivered_at)}</span>
                </div>
              </div>
            ))}
            <div className="pagination">
              <button id="alerts-prev" className="btn btn-secondary btn-sm" disabled={page === 1} onClick={() => setPage(p => p - 1)}>← Prev</button>
              <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                Page {page} of {Math.ceil(total / PAGE_SIZE) || 1}
              </span>
              <button id="alerts-next" className="btn btn-secondary btn-sm" disabled={page >= Math.ceil(total / PAGE_SIZE)} onClick={() => setPage(p => p + 1)}>Next →</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ---- Rules Page ----
interface RuleFormData {
  name: string
  description: string
  mode: 'keyword' | 'semantic' | 'llm_agent'
  keywords: string
  similarity_threshold: number
  reference_text: string
  agent_prompt: string
  alert_title: string
  alert_severity: string
  cooldown_seconds: number
  is_active: boolean
}

function RulesPage() {
  const [rules, setRules] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editingRule, setEditingRule] = useState<any | null>(null)
  const [saving, setSaving] = useState(false)

  const emptyForm = (): RuleFormData => ({
    name: '', description: '', mode: 'keyword', keywords: '',
    similarity_threshold: 0.8, reference_text: '', agent_prompt: '',
    alert_title: '', alert_severity: 'medium', cooldown_seconds: 300,
    is_active: true,
  })

  const [form, setForm] = useState<RuleFormData>(emptyForm())

  const load = () => {
    api.getRules().then(r => { setRules(r.data); setLoading(false) }).catch(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const openCreate = () => { setEditingRule(null); setForm(emptyForm()); setShowModal(true) }
  const openEdit = (rule: any) => {
    setEditingRule(rule)
    setForm({
      name: rule.name, description: rule.description ?? '',
      mode: rule.mode, keywords: (rule.keywords ?? []).join(', '),
      similarity_threshold: rule.similarity_threshold ?? 0.8,
      reference_text: rule.reference_text ?? '',
      agent_prompt: rule.agent_prompt ?? '',
      alert_title: rule.alert_title ?? '',
      alert_severity: rule.alert_severity ?? 'medium',
      cooldown_seconds: rule.cooldown_seconds ?? 300,
      is_active: rule.is_active ?? true,
    })
    setShowModal(true)
  }

  const handleSave = async () => {
    setSaving(true)
    const payload: any = {
      name: form.name, description: form.description || null,
      mode: form.mode,
      keywords: form.keywords.split(',').map(k => k.trim()).filter(Boolean),
      similarity_threshold: form.similarity_threshold,
      reference_text: form.reference_text || null,
      agent_prompt: form.agent_prompt || null,
      alert_title: form.alert_title || null,
      alert_severity: form.alert_severity,
      cooldown_seconds: form.cooldown_seconds,
      is_active: form.is_active,
      filter_source_ids: [], filter_severity: [],
    }
    try {
      if (editingRule) await api.updateRule(editingRule.id, payload)
      else await api.createRule(payload)
      load()
      setShowModal(false)
    } catch (e) { console.error(e) }
    setSaving(false)
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this rule?')) return
    await api.deleteRule(id)
    setRules(prev => prev.filter(r => r.id !== id))
  }

  const toggleActive = async (rule: any) => {
    await api.updateRule(rule.id, { ...rule, is_active: !rule.is_active })
    setRules(prev => prev.map(r => r.id === rule.id ? { ...r, is_active: !r.is_active } : r))
  }

  return (
    <div>
      <div className="section-header">
        <div>
          <h1 className="page-title">Alert Rules</h1>
          <p className="page-subtitle">Define keyword, semantic, or AI-based alert conditions</p>
        </div>
        <button id="create-rule" className="btn btn-primary" onClick={openCreate}>+ New Rule</button>
      </div>

      <div className="table-container">
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}>
            <div className="spinner" />
          </div>
        ) : rules.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">📋</div>
            <h3>No rules yet</h3>
            <p>Create your first alert rule to start monitoring</p>
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Mode</th>
                <th>Severity</th>
                <th>Cooldown</th>
                <th>Last Fired</th>
                <th>Active</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rules.map(rule => (
                <tr key={rule.id} id={`rule-row-${rule.id}`}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{rule.name}</div>
                    {rule.description && (
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                        {rule.description}
                      </div>
                    )}
                    {rule.mode === 'keyword' && rule.keywords?.length > 0 && (
                      <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        {rule.keywords.slice(0, 4).map((k: string) => (
                          <span key={k} className="tag">{k}</span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td><ModeBadge mode={rule.mode} /></td>
                  <td><SeverityBadge severity={rule.alert_severity} /></td>
                  <td style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                    {rule.cooldown_seconds}s
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {rule.last_fired_at ? formatRelative(rule.last_fired_at) : '—'}
                  </td>
                  <td>
                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={rule.is_active}
                        onChange={() => toggleActive(rule)}
                        id={`rule-toggle-${rule.id}`}
                      />
                      <span className="toggle-slider" />
                    </label>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button
                        id={`edit-rule-${rule.id}`}
                        className="btn btn-secondary btn-sm"
                        onClick={() => openEdit(rule)}
                      >Edit</button>
                      <button
                        id={`delete-rule-${rule.id}`}
                        className="btn btn-danger btn-sm"
                        onClick={() => handleDelete(rule.id)}
                      >Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowModal(false)}>
          <div className="modal" id="rule-modal">
            <div className="modal-header">
              <span style={{ fontSize: 16, fontWeight: 700 }}>
                {editingRule ? 'Edit Rule' : 'New Alert Rule'}
              </span>
              <button className="btn btn-secondary btn-sm" onClick={() => setShowModal(false)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label className="form-label">Rule Name *</label>
                <input
                  id="rule-name"
                  className="form-control"
                  value={form.name}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  placeholder="e.g. FDA Critical Recall Alert"
                />
              </div>
              <div className="form-group">
                <label className="form-label">Description</label>
                <input
                  id="rule-description"
                  className="form-control"
                  value={form.description}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  placeholder="Optional description"
                />
              </div>
              <div className="grid-2">
                <div className="form-group">
                  <label className="form-label">Evaluation Mode *</label>
                  <select
                    id="rule-mode"
                    className="form-control"
                    value={form.mode}
                    onChange={e => setForm(f => ({ ...f, mode: e.target.value as any }))}
                  >
                    <option value="keyword">Keyword Match</option>
                    <option value="semantic">Semantic Similarity</option>
                    <option value="llm_agent">LLM Agent</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Alert Severity</label>
                  <select
                    id="rule-alert-severity"
                    className="form-control"
                    value={form.alert_severity}
                    onChange={e => setForm(f => ({ ...f, alert_severity: e.target.value }))}
                  >
                    {['info', 'low', 'medium', 'high', 'critical'].map(s => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </div>
              </div>

              {form.mode === 'keyword' && (
                <div className="form-group">
                  <label className="form-label">Keywords (comma-separated)</label>
                  <input
                    id="rule-keywords"
                    className="form-control"
                    value={form.keywords}
                    onChange={e => setForm(f => ({ ...f, keywords: e.target.value }))}
                    placeholder="recall, vulnerability, critical failure"
                  />
                </div>
              )}

              {form.mode === 'semantic' && (
                <>
                  <div className="form-group">
                    <label className="form-label">Reference Text</label>
                    <textarea
                      id="rule-reference-text"
                      className="form-control"
                      value={form.reference_text}
                      onChange={e => setForm(f => ({ ...f, reference_text: e.target.value }))}
                      placeholder="Describe what you're looking for in natural language..."
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">
                      Similarity Threshold: {form.similarity_threshold}
                    </label>
                    <input
                      id="rule-threshold"
                      type="range"
                      min={0.5}
                      max={1.0}
                      step={0.01}
                      value={form.similarity_threshold}
                      onChange={e => setForm(f => ({ ...f, similarity_threshold: parseFloat(e.target.value) }))}
                      style={{ width: '100%', accentColor: 'var(--accent)' }}
                    />
                  </div>
                </>
              )}

              {form.mode === 'llm_agent' && (
                <div className="form-group">
                  <label className="form-label">Agent Instruction</label>
                  <textarea
                    id="rule-agent-prompt"
                    className="form-control"
                    value={form.agent_prompt}
                    onChange={e => setForm(f => ({ ...f, agent_prompt: e.target.value }))}
                    placeholder="Alert if this event involves a product recall affecting more than 1000 units..."
                  />
                </div>
              )}

              <div className="grid-2">
                <div className="form-group">
                  <label className="form-label">Alert Title</label>
                  <input
                    id="rule-alert-title"
                    className="form-control"
                    value={form.alert_title}
                    onChange={e => setForm(f => ({ ...f, alert_title: e.target.value }))}
                    placeholder="Custom alert title"
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Cooldown (seconds)</label>
                  <input
                    id="rule-cooldown"
                    type="number"
                    className="form-control"
                    value={form.cooldown_seconds}
                    onChange={e => setForm(f => ({ ...f, cooldown_seconds: parseInt(e.target.value) || 300 }))}
                    min={0}
                  />
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <label className="toggle">
                  <input
                    id="rule-is-active"
                    type="checkbox"
                    checked={form.is_active}
                    onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))}
                  />
                  <span className="toggle-slider" />
                </label>
                <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Active</span>
              </div>
            </div>
            <div className="modal-footer">
              <button id="cancel-rule" className="btn btn-secondary" onClick={() => setShowModal(false)}>Cancel</button>
              <button
                id="save-rule"
                className="btn btn-primary"
                onClick={handleSave}
                disabled={!form.name || saving}
              >
                {saving ? 'Saving…' : (editingRule ? 'Save Changes' : 'Create Rule')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ---- Sources Page ----
function SourcesPage() {
  const [sources, setSources] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.getSources().then(r => { setSources(r.data); setLoading(false) }).catch(() => setLoading(false))
  }, [])

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 className="page-title">Data Sources</h1>
        <p className="page-subtitle">Configured REST API endpoints being polled</p>
      </div>

      <div className="table-container">
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 60 }}>
            <div className="spinner" />
          </div>
        ) : sources.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">🔗</div>
            <h3>No sources</h3>
            <p>Add data sources via the API or SQL editor</p>
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>URL</th>
                <th>Poll Interval</th>
                <th>Items Path</th>
                <th>Status</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {sources.map(src => (
                <tr key={src.id} id={`source-row-${src.id}`}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{src.name}</div>
                    {src.description && (
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                        {src.description}
                      </div>
                    )}
                  </td>
                  <td>
                    <a
                      href={src.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontSize: 12, color: 'var(--accent-light)', fontFamily: 'monospace' }}
                      className="truncate"
                    >
                      {src.url.length > 60 ? src.url.slice(0, 60) + '…' : src.url}
                    </a>
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                    {src.poll_interval_seconds}s
                  </td>
                  <td>
                    <span className="font-mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      {src.items_path}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${src.is_active ? 'badge-low' : 'badge-info'}`}>
                      {src.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {src.created_at ? formatRelative(src.created_at) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ---- Search Page ----
function SearchPage() {
  const [query, setQuery] = useState('')
  const [threshold, setThreshold] = useState(0.7)
  const [results, setResults] = useState<any[]>([])
  const [searching, setSearching] = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState('')

  const handleSearch = async () => {
    if (!query.trim()) return
    setSearching(true)
    setError('')
    try {
      const r = await api.searchDocuments(query.trim(), threshold, 20)
      setResults(r.data)
      setSearched(true)
    } catch (e: any) {
      setError(e.message || 'Search failed')
    }
    setSearching(false)
  }

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 className="page-title">Semantic Search</h1>
        <p className="page-subtitle">Find relevant documents using AI-powered vector similarity</p>
      </div>

      <div className="card" style={{ marginBottom: 24 }}>
        <div className="card-body">
          <div className="search-box" style={{ marginBottom: 16 }}>
            <span style={{ fontSize: 18 }}>🔍</span>
            <input
              id="search-input"
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder="Search documents by meaning, e.g. 'product safety issues'"
              style={{ flex: 1 }}
            />
            <button
              id="search-btn"
              className="btn btn-primary btn-sm"
              onClick={handleSearch}
              disabled={searching || !query.trim()}
            >
              {searching ? 'Searching…' : 'Search'}
            </button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <label style={{ fontSize: 12, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
              Similarity: {threshold}
            </label>
            <input
              id="search-threshold"
              type="range"
              min={0.5}
              max={1.0}
              step={0.01}
              value={threshold}
              onChange={e => setThreshold(parseFloat(e.target.value))}
              style={{ flex: 1, accentColor: 'var(--accent)' }}
            />
          </div>
        </div>
      </div>

      {error && (
        <div style={{ padding: 16, background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 'var(--radius)', color: 'var(--sev-critical)', marginBottom: 16 }}>
          ⚠ {error}
        </div>
      )}

      {searched && (
        <div>
          <div style={{ marginBottom: 12, fontSize: 13, color: 'var(--text-secondary)' }}>
            {results.length === 0
              ? 'No results found. Try lowering the similarity threshold or using different terms.'
              : `Found ${results.length} result${results.length !== 1 ? 's' : ''} for "${query}"`
            }
          </div>
          <div className="table-container">
            {results.map((doc, i) => (
              <div key={doc.id} id={`search-result-${i}`} style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{doc.title || 'Untitled'}</div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 }}>
                    <span style={{
                      fontSize: 12, fontWeight: 700,
                      color: doc.similarity >= 0.9 ? 'var(--sev-low)' : doc.similarity >= 0.75 ? 'var(--sev-medium)' : 'var(--text-muted)'
                    }}>
                      {(doc.similarity * 100).toFixed(1)}%
                    </span>
                    <SeverityBadge severity={doc.severity} />
                  </div>
                </div>
                {doc.summary && (
                  <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>{doc.summary}</div>
                )}
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>
                  {doc.source_name}
                  {doc.processed_at && ` · ${formatRelative(doc.processed_at)}`}
                </div>
                {doc.tags?.length > 0 && (
                  <div className="event-tags" style={{ marginTop: 8 }}>
                    {doc.tags.slice(0, 6).map((t: string) => (
                      <span key={t} className="tag">{t}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ---- Main App ----
export default function Home() {
  const [page, setPage] = useState<Page>('dashboard')
  const [unreadCount, setUnreadCount] = useState(0)

  // Load initial unread count
  useEffect(() => {
    api.getAlerts({ unread_only: true, page: 1, page_size: 1 })
      .then(r => setUnreadCount(r.total))
      .catch(() => {})
  }, [])

  const refreshUnread = useCallback(() => {
    api.getAlerts({ unread_only: true, page: 1, page_size: 1 })
      .then(r => setUnreadCount(r.total))
      .catch(() => {})
  }, [])

  return (
    <div className="layout">
      <Sidebar page={page} setPage={setPage} unreadCount={unreadCount} />
      <main className="main-content">
        <div className="topbar">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <h2 style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
              {page === 'dashboard' && 'Overview'}
              {page === 'events' && 'Live Event Feed'}
              {page === 'alerts' && 'Alert Log'}
              {page === 'rules' && 'Alert Rules'}
              {page === 'sources' && 'Data Sources'}
              {page === 'search' && 'Semantic Search'}
            </h2>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="live-dot" />
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Realtime active</span>
          </div>
        </div>
        <div className="page-content">
          {page === 'dashboard' && <DashboardPage />}
          {page === 'events'    && <EventsPage />}
          {page === 'alerts'    && <AlertsPage onRead={refreshUnread} />}
          {page === 'rules'     && <RulesPage />}
          {page === 'sources'   && <SourcesPage />}
          {page === 'search'    && <SearchPage />}
        </div>
      </main>
      <ToastContainer />
    </div>
  )
}
