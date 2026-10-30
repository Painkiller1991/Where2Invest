import type { DecisionSnapshot } from '../decisions'

type Props = {
  decisions: DecisionSnapshot[]
  activeId: string | null
  onBack: () => void
  onSelectOverlay: (id: string | null) => void
  onDelete: (id: string) => void
  onUpdate: (id: string, patch: { title?: string; note?: string }) => void
}

function fmtMoney(n: number) {
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('fa-IR', { maximumFractionDigits: 0 })
}

function fmtWhen(ms: number) {
  return new Date(ms).toLocaleString('fa-IR')
}

export default function DecisionsPage({
  decisions,
  activeId,
  onBack,
  onSelectOverlay,
  onDelete,
  onUpdate,
}: Props) {
  return (
    <section className="panel">
      <h2>تصمیمات اتخاذ شده</h2>
      <p className="muted">
        اسنپ‌شات‌های ذخیره‌شده از پیش‌بینی/خرید. با «نمایش روی چارت» مسیر پیش‌بینی آن روز با رنگ جدا روی
        نمودار واقعی صفحهٔ اول می‌افتد تا ماه‌های بعد اختلاف را ببینی.
      </p>
      <div className="row">
        <button type="button" className="ghost" onClick={onBack}>
          برگشت به چارت
        </button>
        {activeId ? (
          <button type="button" className="ghost" onClick={() => onSelectOverlay(null)}>
            برداشتن هم‌پوشانی فعال
          </button>
        ) : null}
      </div>

      {decisions.length === 0 ? (
        <p className="muted">هنوز تصمیمی ذخیره نشده. از مرحلهٔ پیش‌بینی یا مقایسه، «ذخیره تصمیم خرید» را بزن.</p>
      ) : (
        <ul className="decision-list">
          {decisions.map((d) => {
            const active = d.id === activeId
            const g0 = d.gram18.last_close
            const g1 = d.gram18.forecast.at(-1)?.value
            return (
              <li key={d.id} className={`decision-card ${active ? 'active' : ''}`}>
                <div className="decision-card-head">
                  <input
                    className="decision-title"
                    value={d.title}
                    onChange={(e) => onUpdate(d.id, { title: e.target.value })}
                    aria-label="عنوان تصمیم"
                  />
                  <span className="muted decision-when">{fmtWhen(d.created_at)}</span>
                </div>
                <ul className="decision-meta">
                  <li>
                    افق {d.months} ماه · مدل {d.forecast_model} · احساس طلا {d.gold_sentiment} / دلار{' '}
                    {d.usd_sentiment}
                  </li>
                  <li>
                    گرم ۱۸ در لحظهٔ تصمیم: <strong>{fmtMoney(g0)}</strong> تومان
                    {g1 != null ? (
                      <>
                        {' '}
                        → پیش‌بینی انتها: <strong>{fmtMoney(g1)}</strong>
                      </>
                    ) : null}
                  </li>
                  <li>
                    انس {fmtMoney(d.gold.last_close)} · دلار {fmtMoney(d.usd.last_close)}
                  </li>
                  {d.invest?.recommendation ? (
                    <li className="decision-rec">{d.invest.recommendation}</li>
                  ) : null}
                </ul>
                <label className="decision-note-label">
                  یادداشت
                  <textarea
                    rows={2}
                    value={d.note}
                    onChange={(e) => onUpdate(d.id, { note: e.target.value })}
                    placeholder="چرا این تصمیم را گرفتی…"
                  />
                </label>
                <div className="row">
                  <button
                    type="button"
                    className={active ? 'primary' : 'ghost'}
                    onClick={() => onSelectOverlay(active ? null : d.id)}
                  >
                    {active ? 'هم‌پوشانی فعال ✓' : 'نمایش روی چارت واقعی'}
                  </button>
                  <button
                    type="button"
                    className="ghost danger-ghost"
                    onClick={() => {
                      if (window.confirm('این تصمیم حذف شود؟')) onDelete(d.id)
                    }}
                  >
                    حذف
                  </button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
