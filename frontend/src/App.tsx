import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  type DataStatus,
  type ForecastPoint,
  type ForecastResponse,
  type ForecastSeries,
  type InvestCompareResponse,
  type InvestContext,
  type InvestMonthStep,
  type InvestResult,
} from './api'
import TradeChart from './components/TradeChart'

const STEPS = [
  'آپدیت داده و چارت',
  'احساس و پیش‌بینی',
  'مدل‌های سرمایه‌گذاری',
  'مقایسه سود',
]

const TROY_OZ = 31.1034768

type Flash = { kind: 'success' | 'error' | 'info'; text: string }

function fmtMoney(n: number, digits = 0) {
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('fa-IR', { maximumFractionDigits: digits })
}

function fmtPct(n: number) {
  if (!Number.isFinite(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(1)}٪`
}

function fmtDate(ts: number) {
  if (!Number.isFinite(ts) || ts <= 0) return '—'
  return new Date(ts * 1000).toLocaleDateString('fa-IR')
}

type ForecastRangeStats = {
  avg: number
  min: number
  minTime: number
  max: number
  maxTime: number
  n: number
}

function computeForecastStats(points: ForecastPoint[]): ForecastRangeStats | null {
  if (!points?.length) return null
  let min = points[0]
  let max = points[0]
  let sum = 0
  for (const p of points) {
    sum += p.value
    if (p.value < min.value) min = p
    if (p.value > max.value) max = p
  }
  return {
    avg: sum / points.length,
    min: min.value,
    minTime: min.time,
    max: max.value,
    maxTime: max.time,
    n: points.length,
  }
}

function RangeField({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  display,
}: {
  label: string
  value: number
  onChange: (n: number) => void
  min: number
  max: number
  step?: number
  display?: string
}) {
  return (
    <label className="range-field">
      <div className="range-head">
        <span>{label}</span>
        <strong dir="ltr">{display ?? String(value)}</strong>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <div className="range-ends" dir="ltr">
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </label>
  )
}

function ForecastStatsCard({
  title,
  unit,
  series,
  digits = 0,
}: {
  title: string
  unit: string
  series: ForecastSeries
  digits?: number
}) {
  const stats = useMemo(() => computeForecastStats(series.forecast || []), [series.forecast])
  if (!stats) return null
  return (
    <div className="forecast-stats">
      <p className="forecast-stats-title">{title}</p>
      <ul>
        <li>
          میانگین بازه پیش‌بینی: <strong>{fmtMoney(stats.avg, digits)}</strong> {unit}
        </li>
        <li>
          کمینه: <strong>{fmtMoney(stats.min, digits)}</strong> {unit}
          <span className="muted"> — {fmtDate(stats.minTime)}</span>
        </li>
        <li>
          بیشینه: <strong>{fmtMoney(stats.max, digits)}</strong> {unit}
          <span className="muted"> — {fmtDate(stats.maxTime)}</span>
        </li>
      </ul>
    </div>
  )
}

function gram18From(ounce: number, usd: number) {
  if (!(ounce > 0) || !(usd > 0)) return 0
  return ((ounce * usd) / TROY_OZ) * (18 / 24)
}

function buildLocalContext(
  fc: ForecastResponse,
  capital: number,
  monthly: number,
): InvestContext {
  const usdNow = fc.usd.historical.at(-1)?.close ?? 0
  const ozNow = fc.gold.historical.at(-1)?.close ?? 0
  const usdEnd = fc.usd.forecast.at(-1)?.value ?? usdNow
  const ozEnd = fc.gold.forecast.at(-1)?.value ?? ozNow
  const g0 = gram18From(ozNow, usdNow)
  const g1 = gram18From(ozEnd, usdEnd)
  const h = fc.months
  const pct = (a: number, b: number) => (a ? ((b - a) / a) * 100 : 0)
  return {
    horizon_months: h,
    usd_now: usdNow,
    usd_end: usdEnd,
    usd_change_pct: pct(usdNow, usdEnd),
    ounce_now: ozNow,
    ounce_end: ozEnd,
    ounce_change_pct: pct(ozNow, ozEnd),
    gram18_now: g0,
    gram18_end: g1,
    gram18_change_pct: pct(g0, g1),
    capital_toman: capital,
    monthly_budget_toman: monthly,
    total_cash_in: capital + monthly * h,
    capital_as_usd_now: usdNow ? capital / usdNow : 0,
    capital_as_gram18_now: g0 ? capital / g0 : 0,
    monthly_as_usd_now: usdNow ? monthly / usdNow : 0,
    monthly_as_gram18_now: g0 ? monthly / g0 : 0,
    capital_as_usd_end: usdEnd ? capital / usdEnd : 0,
    capital_as_gram18_end: g1 ? capital / g1 : 0,
    monthly_as_usd_end: usdEnd ? monthly / usdEnd : 0,
    monthly_as_gram18_end: g1 ? monthly / g1 : 0,
  }
}

function parseGroupedNumber(raw: string): number {
  const cleaned = raw
    .replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))
    .replace(/[,\u066C\u060C\s]/g, '')
    .replace(/[٫]/g, '.')
  if (cleaned === '' || cleaned === '-' || cleaned === '.') return 0
  const n = Number(cleaned)
  return Number.isFinite(n) ? n : 0
}

function formatGrouped(n: number, digits = 0): string {
  if (!Number.isFinite(n)) return ''
  return n.toLocaleString('en-US', {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  })
}

function MoneyInput({
  value,
  onChange,
  digits = 0,
}: {
  value: number
  onChange: (n: number) => void
  digits?: number
}) {
  const [focused, setFocused] = useState(false)
  const [text, setText] = useState(() => formatGrouped(value, digits))

  useEffect(() => {
    if (!focused) setText(formatGrouped(value, digits))
  }, [value, digits, focused])

  return (
    <input
      type="text"
      inputMode="decimal"
      dir="ltr"
      className="money-input"
      value={focused ? text : formatGrouped(value, digits)}
      onFocus={() => {
        setFocused(true)
        setText(formatGrouped(value, digits))
      }}
      onBlur={() => {
        setFocused(false)
        const n = parseGroupedNumber(text)
        onChange(n)
        setText(formatGrouped(n, digits))
      }}
      onChange={(e) => {
        const raw = e.target.value
        if (raw !== '' && !/^[\d۰-۹,.\u066C\u060C\s]*$/.test(raw)) return
        setText(raw)
        onChange(parseGroupedNumber(raw))
      }}
    />
  )
}

function LoadingBlock({ text }: { text: string }) {
  return (
    <div className="loading-block" role="status" aria-live="polite" aria-busy="true">
      <span className="spinner" aria-hidden="true" />
      <div className="loading-copy">
        <p className="loading-title">{text}</p>
        <p className="loading-sub">لطفاً چند لحظه صبر کنید…</p>
      </div>
    </div>
  )
}

function fmtUnits(n: number, label: string) {
  if (!label || !Number.isFinite(n) || n <= 0) return '—'
  const digits = label.includes('گرم') ? 4 : 2
  return `${n.toLocaleString('fa-IR', { maximumFractionDigits: digits, minimumFractionDigits: digits })} ${label}`
}

function ScenarioTimeline({
  steps,
  result,
}: {
  steps: InvestMonthStep[]
  result: InvestResult
}) {
  if (!steps.length) {
    return <p className="muted">برای این سناریو جزئیات ماهانه ساخته نشد.</p>
  }
  const unitLabel = result.unit_label || steps.find((s) => s.unit_label)?.unit_label || ''
  const showUnits = Boolean(unitLabel)
  const unitsEnd = result.units_held ?? steps.at(-1)?.units_held ?? 0
  const endPrice = result.end_price ?? steps.at(-1)?.price ?? 0
  return (
    <div className="timeline-panel">
      {showUnits && (
        <p className="timeline-summary">
          جمع موجودی پایان افق: <strong>{fmtUnits(unitsEnd, unitLabel)}</strong>
          {endPrice > 0 ? (
            <>
              {' '}
              — قیمت پایان ≈ {fmtMoney(endPrice)} تومان
              {' '}
              — ارزش ریالی ≈ <strong>{fmtMoney(result.end_value)}</strong> تومان
            </>
          ) : (
            <>
              {' '}
              — ارزش ریالی ≈ <strong>{fmtMoney(result.end_value)}</strong> تومان
            </>
          )}
        </p>
      )}
      <div className="timeline-wrap">
        <table className="timeline">
          <thead>
            <tr>
              <th>ماه</th>
              <th>رویدادها</th>
              <th>ورود نقد</th>
              <th>خرید (تومان)</th>
              {showUnits && <th>خرید ({unitLabel})</th>}
              {showUnits && <th>موجودی ({unitLabel})</th>}
              <th>قسط</th>
              <th>امتیاز</th>
              <th>سپرده</th>
              <th>بدهی</th>
              <th>ارزش ریالی</th>
              <th>ثروت</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((s) => (
              <tr key={s.month}>
                <td>{s.label || `ماه ${s.month}`}</td>
                <td className="timeline-events">
                  {(s.events || []).map((e, i) => (
                    <div key={i}>{e}</div>
                  ))}
                </td>
                <td>{fmtMoney(s.cash_in)}</td>
                <td>{fmtMoney(s.buy)}</td>
                {showUnits && <td>{fmtUnits(s.units_bought, unitLabel)}</td>}
                {showUnits && <td>{fmtUnits(s.units_held, unitLabel)}</td>}
                <td>{s.installment ? fmtMoney(s.installment) : '—'}</td>
                <td>{s.points ? s.points.toFixed(1) : '—'}</td>
                <td>{s.deposit ? fmtMoney(s.deposit) : '—'}</td>
                <td>{s.debt ? fmtMoney(s.debt) : '—'}</td>
                <td>{fmtMoney(s.asset_value)}</td>
                <td>{fmtMoney(s.wealth)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ResultsTable({
  results,
  bestMethod,
  expanded,
  onToggle,
}: {
  results: InvestResult[]
  bestMethod: string
  expanded: string | null
  onToggle: (method: string) => void
}) {
  return (
    <table className="results">
      <thead>
        <tr>
          <th></th>
          <th>روش / دارایی</th>
          <th>قابل سرمایه‌گذاری</th>
          <th>پایان</th>
          <th>سود خالص</th>
          <th>درصد</th>
          <th>یادداشت</th>
        </tr>
      </thead>
      <tbody>
        {results.map((r) => {
          const open = expanded === r.method
          return (
            <Fragment key={r.method}>
              <tr
                className={`${r.method === bestMethod ? 'best' : ''} ${r.valid === false ? 'invalid' : ''} ${open ? 'open' : ''}`}
              >
                <td>
                  <button
                    type="button"
                    className="expand-btn"
                    aria-expanded={open}
                    onClick={() => onToggle(r.method)}
                    title={open ? 'بستن جزئیات ماهانه' : 'باز کردن جزئیات ماهانه'}
                  >
                    {open ? '▾' : '▸'}
                  </button>
                </td>
                <td>
                  <button type="button" className="linkish" onClick={() => onToggle(r.method)}>
                    {r.title}
                  </button>
                </td>
                <td>{fmtMoney(r.investable)}</td>
                <td>{fmtMoney(r.end_value)}</td>
                <td>{fmtMoney(r.net_profit)}</td>
                <td>{Number.isFinite(r.profit_pct) ? `${r.profit_pct.toFixed(2)}%` : '—'}</td>
                <td>{r.notes}</td>
              </tr>
              {open && (
                <tr className="timeline-row">
                  <td colSpan={7}>
                    <ScenarioTimeline steps={r.timeline || []} result={r} />
                  </td>
                </tr>
              )}
            </Fragment>
          )
        })}
      </tbody>
    </table>
  )
}

function ContextFacts({ ctx }: { ctx: InvestContext }) {
  return (
    <div className="facts">
      <p className="facts-title">جزئیات ثابت از روی پیش‌بینی و پول‌ها</p>
      <ul className="facts-list">
        <li>
          افق پیش‌بینی: <strong>{ctx.horizon_months} ماه</strong>
        </li>
        <li>
          دلار آزاد الان {fmtMoney(ctx.usd_now)} تومان → انتهای افق {fmtMoney(ctx.usd_end)} (
          {fmtPct(ctx.usd_change_pct)})
        </li>
        <li>
          گرم ۱۸ الان {fmtMoney(ctx.gram18_now)} تومان → انتهای افق {fmtMoney(ctx.gram18_end)} (
          {fmtPct(ctx.gram18_change_pct)})
        </li>
        <li>
          انس جهانی {fmtMoney(ctx.ounce_now, 1)} → {fmtMoney(ctx.ounce_end, 1)} دلار (
          {fmtPct(ctx.ounce_change_pct)})
        </li>
        <li>
          سرمایه {fmtMoney(ctx.capital_toman)} تومان ≈ الان {fmtMoney(ctx.capital_as_usd_now, 1)} دلار یا{' '}
          {fmtMoney(ctx.capital_as_gram18_now, 2)} گرم طلا
        </li>
        <li>
          بودجه ماهانه {fmtMoney(ctx.monthly_budget_toman)} تومان ≈ الان{' '}
          {fmtMoney(ctx.monthly_as_usd_now, 1)} دلار یا {fmtMoney(ctx.monthly_as_gram18_now, 3)} گرم؛ با قیمت
          انتهای افق ≈ {fmtMoney(ctx.monthly_as_usd_end, 1)} دلار / {fmtMoney(ctx.monthly_as_gram18_end, 3)} گرم
        </li>
        <li>
          جمع پول ورودی تا افق (سرمایه + بودجه×ماه): <strong>{fmtMoney(ctx.total_cash_in)} تومان</strong>
        </li>
      </ul>
    </div>
  )
}

export default function App() {
  const [step, setStep] = useState(0)
  const [startDate, setStartDate] = useState('2018-01-01')
  const [loading, setLoading] = useState(false)
  const [flash, setFlash] = useState<Flash | null>(null)
  const flashTimer = useRef<number | null>(null)
  const [status, setStatus] = useState<DataStatus | null>(null)
  const [configText, setConfigText] = useState('')
  const [showConfig, setShowConfig] = useState(false)

  const showFlash = useCallback((kind: Flash['kind'], text: string, autoHideMs = 5000) => {
    setFlash({ kind, text })
    if (flashTimer.current) window.clearTimeout(flashTimer.current)
    if (kind !== 'error' && autoHideMs > 0) {
      flashTimer.current = window.setTimeout(() => setFlash(null), autoHideMs)
    }
  }, [])

  const [goldSentiment, setGoldSentiment] = useState(0)
  const [usdSentiment, setUsdSentiment] = useState(0)
  const [months, setMonths] = useState(3)
  const [forecastModel, setForecastModel] = useState<
    'hybrid' | 'auto' | 'lightgbm' | 'prophet' | 'both' | 'drift'
  >('hybrid')
  const [forecast, setForecast] = useState<ForecastResponse | null>(null)

  const [capital, setCapital] = useState(100_000_000)
  const [monthlyBudget, setMonthlyBudget] = useState(0)
  const [budgetConfirmed, setBudgetConfirmed] = useState(false)
  const [fundAnnual, setFundAnnual] = useState(20)
  const [enableGold, setEnableGold] = useState(true)
  const [enableUsd, setEnableUsd] = useState(true)
  const [enableFund, setEnableFund] = useState(true)
  const [enableFintech, setEnableFintech] = useState(true)
  const [enableDirect, setEnableDirect] = useState(true)
  const [enableBankToBank, setEnableBankToBank] = useState(true)
  const [enableBankToAsset, setEnableBankToAsset] = useState(true)
  const [loanAmount, setLoanAmount] = useState(100_000_000)
  const [companyFeePct, setCompanyFeePct] = useState(5)
  const [bankAnnualPct, setBankAnnualPct] = useState(22)
  const [repayMonths, setRepayMonths] = useState(12)
  const [feeSource, setFeeSource] = useState<'from_loan' | 'cash'>('from_loan')
  const [tomanPerPoint, setTomanPerPoint] = useState(100_000)
  const [pointsForLoan, setPointsForLoan] = useState(100)
  const [loanForPoints, setLoanForPoints] = useState(100_000_000)
  const [model3BankAnnual, setModel3BankAnnual] = useState(0)
  const [invest, setInvest] = useState<InvestCompareResponse | null>(null)
  const [calcNote, setCalcNote] = useState<string | null>(null)
  const [expandedMethod, setExpandedMethod] = useState<string | null>(null)
  const resultsRef = useRef<HTMLElement | null>(null)

  const localContext = useMemo(() => {
    if (!forecast?.confirmed) return null
    return buildLocalContext(forecast, capital, monthlyBudget)
  }, [forecast, capital, monthlyBudget])

  const investPayload = () => ({
    capital_toman: capital,
    monthly_budget_toman: monthlyBudget,
    fund_annual_pct: fundAnnual,
    enable_gold: enableGold,
    enable_usd: enableUsd,
    enable_fund: enableFund,
    enable_fintech: enableFintech,
    enable_direct: enableDirect,
    enable_bank_to_bank: enableBankToBank,
    enable_bank_to_asset: enableBankToAsset,
    loan_amount: loanAmount,
    company_fee_pct: companyFeePct,
    bank_annual_pct: bankAnnualPct,
    repay_months: repayMonths,
    fee_source: feeSource,
    toman_per_point: tomanPerPoint,
    points_for_loan: pointsForLoan,
    loan_for_points: loanForPoints,
    model3_bank_annual_pct: model3BankAnnual,
  })

  const refreshStatus = useCallback(async () => {
    const s = await api.dataStatus()
    setStatus(s)
    return s
  }, [])

  useEffect(() => {
    ;(async () => {
      try {
        const cfg = await api.getConfig()
        const data = cfg.data as { history?: { start_date?: string } } | undefined
        const sd = data?.history?.start_date
        if (sd) setStartDate(sd)
        setConfigText(JSON.stringify(cfg, null, 2))
        await refreshStatus()
        setLoading(true)
        setCalcNote('در حال بارگذاری / آپدیت داده از دیتابیس...')
        const s = await api.fetchData(sd, false)
        setStatus(s)
        if (!s.ready) {
          showFlash('error', s.error || 'دریافت داده ناموفق بود')
        } else {
          const mode =
            s.updated === 'full'
              ? 'دانلود کامل'
              : s.updated === 'incremental'
                ? 'آپدیت افزایشی'
                : 'بارگذاری از دیتابیس'
          showFlash('success', `داده آماده شد — ${mode}`)
        }
      } catch (e) {
        showFlash('error', 'خطا در شروع: ' + String(e))
      } finally {
        setCalcNote(null)
        setLoading(false)
      }
    })()
  }, [refreshStatus, showFlash])

  const dataReady = Boolean(status?.ready)

  const runFetch = async (force = false) => {
    setLoading(true)
    setCalcNote(force ? 'در حال دانلود کامل...' : 'در حال آپدیت افزایشی...')
    try {
      const s = await api.fetchData(startDate, force)
      setStatus(s)
      if (!s.ready) {
        showFlash('error', s.error || 'عملیات ناموفق بود. دوباره تلاش کنید.')
      } else {
        const mode =
          s.updated === 'full'
            ? 'دانلود کامل انجام شد'
            : s.updated === 'incremental'
              ? 'آپدیت افزایشی موفق بود (فقط روزهای جدید)'
              : 'داده از قبل به‌روز بود (از دیتابیس)'
        const range = s.gold ? `${s.gold.start_date} → ${s.gold.end_date}` : ''
        showFlash('success', `${mode}${range ? ` — ${range}` : ''}`)
      }
    } catch (e) {
      showFlash('error', 'خطا: ' + String(e))
    } finally {
      setCalcNote(null)
      setLoading(false)
    }
  }

  const updatedLabel =
    status?.updated === 'full'
      ? 'دانلود کامل'
      : status?.updated === 'incremental'
        ? 'آپدیت افزایشی'
        : status?.updated === 'cache'
          ? 'از دیتابیس'
          : null

  const saveConfigJson = async () => {
    setLoading(true)
    setCalcNote('در حال ذخیره کانفیگ...')
    try {
      const parsed = JSON.parse(configText) as Record<string, unknown>
      await api.putConfig(parsed)
      setShowConfig(false)
      showFlash('success', 'کانفیگ با موفقیت ذخیره شد.')
    } catch (e) {
      showFlash('error', 'ذخیره کانفیگ ناموفق: ' + String(e))
    } finally {
      setCalcNote(null)
      setLoading(false)
    }
  }

  const runForecast = async () => {
    if (!dataReady) return
    setLoading(true)
    setCalcNote('در حال اجرای پیش‌بینی...')
    try {
      const fc = await api.forecast({
        gold_sentiment: goldSentiment,
        usd_sentiment: usdSentiment,
        months,
        model: forecastModel,
      })
      setForecast(fc)
      setStep(1)
      showFlash('success', `پیش‌بینی ${months} ماهه آماده شد — در صورت رضایت تایید کنید.`)
    } catch (e) {
      showFlash('error', 'پیش‌بینی ناموفق: ' + String(e))
    } finally {
      setCalcNote(null)
      setLoading(false)
    }
  }

  const confirmAndContinue = async () => {
    setLoading(true)
    setCalcNote('در حال تایید پیش‌بینی...')
    try {
      const fc = await api.confirmForecast(true)
      setForecast(fc)
      setStep(2)
      showFlash('success', 'پیش‌بینی تایید شد؛ می‌توانید مدل سرمایه‌گذاری را ادامه دهید.')
    } catch (e) {
      showFlash('error', 'تایید ناموفق: ' + String(e))
    } finally {
      setCalcNote(null)
      setLoading(false)
    }
  }

  const suggestBudget = async () => {
    setLoading(true)
    setCalcNote('در حال پیشنهاد بودجه ماهانه از روی اقساط...')
    try {
      const res = await api.investSuggestMonthly(investPayload())
      setMonthlyBudget(Math.ceil(res.suggested_monthly))
      setBudgetConfirmed(false)
      showFlash(
        'success',
        res.suggested_monthly > 0
          ? `پیشنهاد بودجه ماهانه: ${Math.ceil(res.suggested_monthly).toLocaleString('fa-IR')} تومان — تایید کنید.`
          : 'قسط وام فعالی نبود؛ بودجه ماهانه را دستی وارد کنید.',
      )
    } catch (e) {
      showFlash('error', 'پیشنهاد بودجه ناموفق: ' + String(e))
    } finally {
      setCalcNote(null)
      setLoading(false)
    }
  }

  const runInvest = async () => {
    if (!budgetConfirmed) {
      showFlash('error', 'اول بودجه ماهانه را تایید کنید.')
      return
    }
    setLoading(true)
    setCalcNote('در حال محاسبه مسیرها روی پیش‌بینی تاییدشده… صفحه را نبندید.')
    try {
      const body = investPayload()
      const res = await api.investCompare(body)
      setExpandedMethod(res.best_method || res.results?.[0]?.method || null)
      setInvest(res)
      setStep(3)
      setCalcNote(null)
      showFlash('success', 'مقایسه آماده شد. توصیه و جدول پایین‌تر است.', 6000)
      window.setTimeout(() => {
        resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 80)
    } catch (e) {
      setCalcNote(null)
      showFlash('error', 'مقایسه ناموفق: ' + String(e))
    } finally {
      setLoading(false)
    }
  }

  const goStep = (i: number) => {
    if (i > 0 && !dataReady) {
      showFlash('error', 'اول مرحله ۱ باید کامل شود (داده آماده نیست).')
      return
    }
    if (i >= 2 && !forecast?.confirmed) {
      showFlash('error', 'اول پیش‌بینی را در مرحله ۲ تایید کنید.')
      return
    }
    setStep(i)
  }

  const sentimentLabel = (n: number) => {
    if (n > 3) return `${n} · خیلی مثبت`
    if (n > 0) return `${n} · مثبت`
    if (n < -3) return `${n} · خیلی منفی`
    if (n < 0) return `${n} · منفی`
    return `${n} · خنثی`
  }

  const forecastStale = Boolean(
    forecast &&
      (forecast.gold_sentiment !== goldSentiment ||
        forecast.usd_sentiment !== usdSentiment ||
        forecast.months !== months),
  )

  return (
    <div className="app">
      <header className={`hero ${step >= 2 ? 'hero-compact' : ''}`}>
        <div className="hero-bg" />
        <div className="hero-content">
          <p className="brand">Where2Invest</p>
          {step < 2 ? (
            <>
              <h1>کجا سرمایه‌گذاری کنم؟</h1>
              <p className="tagline">دادهٔ انس و دلار آزاد، پیش‌بینی، و مقایسهٔ روش‌های سرمایه‌گذاری — لوکال</p>
            </>
          ) : (
            <h1 className="hero-mini">مدل‌ها و مقایسه سود</h1>
          )}
        </div>
      </header>

      <nav className="steps">
        {STEPS.map((label, i) => (
          <button
            key={label}
            type="button"
            className={`step ${step === i ? 'active' : ''} ${i > 0 && !dataReady ? 'locked' : ''}`}
            onClick={() => goStep(i)}
          >
            <span className="num">{i + 1}</span>
            {label}
          </button>
        ))}
      </nav>

      {/* حین لود فقط LoadingBlock؛ toast آبی info تکراری نشان داده نمی‌شود */}
      {flash && !(loading && flash.kind === 'info') ? (
        <div className={`banner ${flash.kind}`} role="status">
          <span>{flash.text}</span>
          <button type="button" className="banner-close" onClick={() => setFlash(null)} aria-label="بستن">
            ×
          </button>
        </div>
      ) : null}
      {loading ? (
        <div className="sticky-status">
          <LoadingBlock text={calcNote || 'در حال پردازش…'} />
        </div>
      ) : null}

      {step === 0 && (
        <section className="panel">
          <h2>مرحله ۱ — آپدیت داده</h2>
          <p className="muted">تا وقتی داده کامل نشود، مراحل بعد قفل‌اند.</p>
          <div className="row">
            <label>
              از تاریخ
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </label>
            <button type="button" className="primary" onClick={() => runFetch(false)} disabled={loading}>
              آپدیت / تلاش مجدد
            </button>
            <button type="button" className="ghost" onClick={() => runFetch(true)} disabled={loading}>
              دانلود کامل مجدد
            </button>
            <button type="button" className="ghost" onClick={() => setShowConfig((v) => !v)}>
              ویرایش کانفیگ
            </button>
            <a className="ghost linkish" href="/docs-static/prediction-models.html" target="_blank" rel="noreferrer">
              مقایسه مدل‌های پیش‌بینی
            </a>
          </div>

          {showConfig && (
            <div className="config-box">
              <textarea value={configText} onChange={(e) => setConfigText(e.target.value)} rows={16} />
              <button type="button" className="primary" onClick={saveConfigJson}>
                ذخیره کانفیگ
              </button>
            </div>
          )}

          {status?.ready && status.gold && status.usd ? (
            <>
              <div className="meta">
                <span>شروع مؤثر: {status.effective_start}</span>
                {updatedLabel ? <span>حالت: {updatedLabel}</span> : null}
                <span>طلا: {status.gold.source}</span>
                <span>دلار: {status.usd.source}</span>
                <span>
                  {status.gold.start_date} → {status.gold.end_date}
                </span>
              </div>
              <TradeChart
                title={status.gold.title}
                symbol="XAU/USD"
                unit={status.gold.unit}
                candles={status.gold.candles}
              />
              <TradeChart
                title={status.usd.title}
                symbol="USD/IRT"
                unit={status.usd.unit}
                candles={status.usd.candles}
              />
              <div className="row">
                <button type="button" className="primary" onClick={() => setStep(1)}>
                  ادامه به پیش‌بینی
                </button>
              </div>
            </>
          ) : (
            <div className="empty">
              {status?.error ? <p>خطا: {status.error} (تلاش‌ها: {status.attempts})</p> : <p>هنوز داده‌ای بارگذاری نشده.</p>}
            </div>
          )}
        </section>
      )}

      {step === 1 && (
        <section className="panel">
          <h2>مرحله ۲ — احساس، پیش‌بینی و تایید</h2>
          <p className="muted">اسلایدرها را بکش، پیش‌بینی بزن، نتیجه را ببین؛ اگر راضی بودی تایید کن.</p>

          <div className="range-grid">
            <RangeField
              label="احساس طلا"
              value={goldSentiment}
              min={-10}
              max={10}
              onChange={setGoldSentiment}
              display={sentimentLabel(goldSentiment)}
            />
            <RangeField
              label="احساس دلار"
              value={usdSentiment}
              min={-10}
              max={10}
              onChange={setUsdSentiment}
              display={sentimentLabel(usdSentiment)}
            />
            <RangeField
              label="افق پیش‌بینی (ماه)"
              value={months}
              min={1}
              max={36}
              onChange={setMonths}
              display={`${months} ماه`}
            />
            <label className="range-field">
              <div className="range-head">
                <span>مدل پیش‌بینی</span>
              </div>
              <select
                value={forecastModel}
                onChange={(e) => setForecastModel(e.target.value as typeof forecastModel)}
              >
                <option value="hybrid">Hybrid (بافت تاریخی + احساس)</option>
                <option value="auto">Auto (Hybrid + LightGBM)</option>
                <option value="both">Hybrid + LightGBM</option>
                <option value="lightgbm">LightGBM (بازده + بافت)</option>
                <option value="prophet">Prophet (بدون فصلی سالانه)</option>
                <option value="drift">Drift + بافت</option>
              </select>
            </label>
          </div>

          <div className="row">
            <button type="button" className="primary" onClick={runForecast} disabled={loading || !dataReady}>
              {forecast ? 'اجرای دوباره پیش‌بینی' : 'اجرای پیش‌بینی'}
            </button>
            <button type="button" className="ghost" onClick={() => setStep(0)}>
              برگشت به چارت
            </button>
          </div>
          {forecastStale && (
            <p className="muted">اسلایدرها عوض شده‌اند — برای دیدن نتیجهٔ جدید دوباره «اجرای پیش‌بینی» را بزن.</p>
          )}

          {forecast && (
            <>
              <p className="muted">
                مدل طلا: {forecast.gold.model_used} | مدل دلار: {forecast.usd.model_used}
                {forecast.confirmed ? ' | تاییدشده' : ' | هنوز تایید نشده'}
              </p>
              <div className="forecast-stats-row">
                <ForecastStatsCard
                  title="آمار پیش‌بینی انس طلا"
                  unit={forecast.gold.unit}
                  series={forecast.gold}
                  digits={1}
                />
                <ForecastStatsCard
                  title="آمار پیش‌بینی دلار آزاد"
                  unit="تومان"
                  series={forecast.usd}
                />
              </div>
              <TradeChart
                title="انس طلا — واقعی / پیش‌بینی"
                symbol="XAU/USD"
                unit={forecast.gold.unit}
                candles={forecast.gold.historical}
                forecast={forecast.gold.forecast}
              />
              <TradeChart
                title="دلار آزاد — واقعی / پیش‌بینی"
                symbol="USD/IRT"
                unit={forecast.usd.unit}
                candles={forecast.usd.historical}
                forecast={forecast.usd.forecast}
              />
              <div className="row">
                <button
                  type="button"
                  className="primary"
                  onClick={() => (forecast.confirmed && !forecastStale ? setStep(2) : confirmAndContinue())}
                  disabled={loading || forecastStale}
                >
                  {forecast.confirmed && !forecastStale
                    ? 'رفتن به مدل‌های سرمایه‌گذاری'
                    : 'تایید پیش‌بینی و ادامه'}
                </button>
              </div>
            </>
          )}
        </section>
      )}

      {step === 2 && (
        <section className="panel">
          <h2>مرحله ۳ — مدل‌های سرمایه‌گذاری</h2>
          <p className="muted">
            سه روش (فین‌تک، خرید مستقیم، بانک→وام) × طلا / دلار / صندوق. بودجه ماهانه برای مقایسه عادلانه مشترک است.
          </p>
          {localContext && <ContextFacts ctx={localContext} />}

          <h3 className="subhead">مشترک</h3>
          <div className="row form-grid">
            <label>
              سرمایه اولیه (تومان)
              <MoneyInput
                value={capital}
                onChange={(n) => {
                  setCapital(n)
                  setBudgetConfirmed(false)
                }}
              />
            </label>
            <label>
              نرخ سالانه صندوق (%)
              <input type="number" value={fundAnnual} onChange={(e) => setFundAnnual(Number(e.target.value))} />
            </label>
            <label>
              بودجه ماهانه (تومان)
              <MoneyInput
                value={monthlyBudget}
                onChange={(n) => {
                  setMonthlyBudget(n)
                  setBudgetConfirmed(false)
                }}
              />
            </label>
          </div>
          <div className="row checks">
            <label className="check">
              <input type="checkbox" checked={enableGold} onChange={(e) => setEnableGold(e.target.checked)} />
              طلای گرم ۱۸
            </label>
            <label className="check">
              <input type="checkbox" checked={enableUsd} onChange={(e) => setEnableUsd(e.target.checked)} />
              دلار آزاد
            </label>
            <label className="check">
              <input type="checkbox" checked={enableFund} onChange={(e) => setEnableFund(e.target.checked)} />
              صندوق درآمد ثابت
            </label>
          </div>
          <div className="row">
            <button type="button" className="ghost" onClick={suggestBudget} disabled={loading}>
              پیشنهاد بودجه = مکس اقساط
            </button>
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setBudgetConfirmed(true)
                showFlash(
                  'success',
                  `بودجه ماهانه ${monthlyBudget.toLocaleString('fa-IR')} تومان تایید شد.`,
                )
              }}
            >
              {budgetConfirmed ? 'بودجه تایید شده ✓' : 'تایید بودجه ماهانه'}
            </button>
          </div>

          <h3 className="subhead">
            <label className="check inline">
              <input type="checkbox" checked={enableFintech} onChange={(e) => setEnableFintech(e.target.checked)} />
              ۱) وام فین‌تک
            </label>
          </h3>
          {enableFintech && (
            <div className="row form-grid">
              <label>
                مبلغ وام
                <MoneyInput
                  value={loanAmount}
                  onChange={(n) => {
                    setLoanAmount(n)
                    setBudgetConfirmed(false)
                  }}
                />
              </label>
              <label>
                کارمزد شرکت (%)
                <input type="number" value={companyFeePct} onChange={(e) => setCompanyFeePct(Number(e.target.value))} />
              </label>
              <label>
                سود بانکی سالانه (%)
                <input
                  type="number"
                  value={bankAnnualPct}
                  onChange={(e) => {
                    setBankAnnualPct(Number(e.target.value))
                    setBudgetConfirmed(false)
                  }}
                />
              </label>
              <label>
                مدت بازپرداخت (ماه)
                <input
                  type="number"
                  value={repayMonths}
                  onChange={(e) => {
                    setRepayMonths(Number(e.target.value))
                    setBudgetConfirmed(false)
                  }}
                />
              </label>
              <label>
                منبع کارمزد
                <select
                  value={feeSource}
                  onChange={(e) => setFeeSource(e.target.value as 'from_loan' | 'cash')}
                >
                  <option value="from_loan">از خود وام</option>
                  <option value="cash">از نقد اولیه</option>
                </select>
              </label>
            </div>
          )}

          <h3 className="subhead">
            <label className="check inline">
              <input type="checkbox" checked={enableDirect} onChange={(e) => setEnableDirect(e.target.checked)} />
              ۲) خرید مستقیم (+ DCA ماهانه)
            </label>
          </h3>

          <h3 className="subhead">۳) پول در بانک → وام</h3>
          <div className="row checks">
            <label className="check">
              <input
                type="checkbox"
                checked={enableBankToBank}
                onChange={(e) => setEnableBankToBank(e.target.checked)}
              />
              ۳الف — ماهانه به بانک
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={enableBankToAsset}
                onChange={(e) => setEnableBankToAsset(e.target.checked)}
              />
              ۳ب — ماهانه دارایی
            </label>
          </div>
          {(enableBankToBank || enableBankToAsset) && (
            <>
              <div className="row form-grid">
                <label>
                  تومان موجودی = ۱ امتیاز / روز
                  <MoneyInput
                    value={tomanPerPoint}
                    onChange={(n) => {
                      setTomanPerPoint(n)
                      setBudgetConfirmed(false)
                    }}
                  />
                </label>
                <label>
                  چند امتیاز برای وام
                  <MoneyInput
                    value={pointsForLoan}
                    onChange={(n) => {
                      setPointsForLoan(n)
                      setBudgetConfirmed(false)
                    }}
                  />
                </label>
                <label>
                  با آن امتیاز چقدر وام (تومان)
                  <MoneyInput
                    value={loanForPoints}
                    onChange={(n) => {
                      setLoanForPoints(n)
                      setBudgetConfirmed(false)
                    }}
                  />
                </label>
                <label>
                  سود وام بانکی مدل۳ (%) — ۰ = بدون قسط
                  <input
                    type="number"
                    value={model3BankAnnual}
                    onChange={(e) => {
                      setModel3BankAnnual(Number(e.target.value))
                      setBudgetConfirmed(false)
                    }}
                  />
                </label>
              </div>
              <p className="muted">
                امتیاز روزانه = موجودی ÷ نرخ بالا؛ هر ماه ≈ همان × ۳۰ روز، تا به امتیاز لازم برسد
                {pointsForLoan > 0
                  ? ` (هر امتیاز ≈ ${(loanForPoints / pointsForLoan).toLocaleString('fa-IR')} تومان وام).`
                  : '.'}
                {tomanPerPoint > 0 && capital > 0 && pointsForLoan > 0
                  ? ` با سرمایه فعلی ≈ ${Math.floor(capital / tomanPerPoint).toLocaleString('fa-IR')} امتیاز/روز (~${Math.floor((capital / tomanPerPoint) * 30).toLocaleString('fa-IR')} /ماه)؛ برای ${pointsForLoan.toLocaleString('fa-IR')} امتیاز مسیر ۳ب حدود ${Math.ceil(pointsForLoan / ((capital / tomanPerPoint) * 30)).toLocaleString('fa-IR')} ماه.`
                  : ''}
              </p>
            </>
          )}

          <div className="row">
            <button type="button" className="primary" onClick={runInvest} disabled={loading || !budgetConfirmed}>
              محاسبه و مقایسه سود
            </button>
          </div>
        </section>
      )}

      {step === 3 && (
        <section className="panel" ref={resultsRef}>
          <h2>مرحله ۴ — مقایسه سود</h2>
          {!invest && !loading && (
            <p className="muted">هنوز نتیجه‌ای نیست. از مرحله ۳ محاسبه را بزنید.</p>
          )}
          {invest && (
            <>
              {(invest.context || localContext) && (
                <ContextFacts ctx={invest.context || localContext!} />
              )}
              {invest.recommendation && (
                <div className="recommend">
                  <p className="recommend-label">توصیه</p>
                  <p className="recommend-msg">{invest.recommendation.message}</p>
                </div>
              )}
              {!invest.recommendation && (
                <p className="muted">هیچ ردیف معتبری برای توصیه باقی نماند؛ جدول را برای جزئیات ببینید.</p>
              )}
              <p className="muted">روی ▸ یا عنوان هر سناریو بزن تا ببینی هر ماه چه اتفاقی می‌افتد.</p>
              <ResultsTable
                results={invest.results || []}
                bestMethod={invest.best_method}
                expanded={expandedMethod}
                onToggle={(method) => setExpandedMethod((cur) => (cur === method ? null : method))}
              />
            </>
          )}
          <div className="row">
            <button type="button" className="ghost" onClick={() => setStep(2)}>
              تغییر ورودی سرمایه‌گذاری
            </button>
            <button type="button" className="ghost" onClick={() => setStep(1)}>
              پیش‌بینی دوباره
            </button>
          </div>
        </section>
      )}

      <footer className="footer">Where2Invest · لوکال · FastAPI + React + KLineChart</footer>
    </div>
  )
}
