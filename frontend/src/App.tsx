import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api,
  type DataStatus,
  type ForecastResponse,
  type InvestCompareResponse,
} from './api'
import TradeChart from './components/TradeChart'

const STEPS = [
  'آپدیت داده و چارت',
  'احساس و پیش‌بینی',
  'تایید پیش‌بینی',
  'مدل‌های سرمایه‌گذاری',
  'مقایسه سود',
]

type Flash = { kind: 'success' | 'error' | 'info'; text: string }

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
  const [loanPerPoint, setLoanPerPoint] = useState(1_000_000)
  const [waitMonths, setWaitMonths] = useState(3)
  const [model3BankAnnual, setModel3BankAnnual] = useState(0)
  const [invest, setInvest] = useState<InvestCompareResponse | null>(null)

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
    loan_per_point: loanPerPoint,
    wait_months: waitMonths,
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
        showFlash('info', 'در حال بارگذاری / آپدیت داده از دیتابیس...')
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
        setLoading(false)
      }
    })()
  }, [refreshStatus, showFlash])

  const dataReady = Boolean(status?.ready)

  const runFetch = async (force = false) => {
    setLoading(true)
    showFlash('info', force ? 'در حال دانلود کامل...' : 'در حال آپدیت افزایشی...')
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
    showFlash('info', 'در حال ذخیره کانفیگ...')
    try {
      const parsed = JSON.parse(configText) as Record<string, unknown>
      await api.putConfig(parsed)
      setShowConfig(false)
      showFlash('success', 'کانفیگ با موفقیت ذخیره شد.')
    } catch (e) {
      showFlash('error', 'ذخیره کانفیگ ناموفق: ' + String(e))
    } finally {
      setLoading(false)
    }
  }

  const runForecast = async () => {
    if (!dataReady) return
    setLoading(true)
    showFlash('info', 'در حال اجرای پیش‌بینی...')
    try {
      const fc = await api.forecast({
        gold_sentiment: goldSentiment,
        usd_sentiment: usdSentiment,
        months,
        model: 'both',
      })
      setForecast(fc)
      setStep(2)
      showFlash('success', `پیش‌بینی ${months} ماهه آماده شد.`)
    } catch (e) {
      showFlash('error', 'پیش‌بینی ناموفق: ' + String(e))
    } finally {
      setLoading(false)
    }
  }

  const confirmAndContinue = async () => {
    setLoading(true)
    showFlash('info', 'در حال تایید پیش‌بینی...')
    try {
      const fc = await api.confirmForecast(true)
      setForecast(fc)
      setStep(3)
      showFlash('success', 'پیش‌بینی تایید شد؛ می‌توانید مدل سرمایه‌گذاری را ادامه دهید.')
    } catch (e) {
      showFlash('error', 'تایید ناموفق: ' + String(e))
    } finally {
      setLoading(false)
    }
  }

  const suggestBudget = async () => {
    setLoading(true)
    showFlash('info', 'در حال پیشنهاد بودجه ماهانه از روی اقساط...')
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
      setLoading(false)
    }
  }

  const runInvest = async () => {
    if (!budgetConfirmed) {
      showFlash('error', 'اول بودجه ماهانه را تایید کنید.')
      return
    }
    setLoading(true)
    showFlash('info', 'در حال مقایسه روش‌های سرمایه‌گذاری...')
    try {
      const res = await api.investCompare(investPayload())
      setInvest(res)
      setStep(4)
      showFlash('success', res.recommendation?.message || 'مقایسه انجام شد.')
    } catch (e) {
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
    if (i >= 3 && !forecast?.confirmed) {
      showFlash('error', 'اول پیش‌بینی را در مرحله ۳ تایید کنید.')
      return
    }
    setStep(i)
  }

  return (
    <div className="app">
      <header className="hero">
        <div className="hero-bg" />
        <div className="hero-content">
          <p className="brand">Where2Invest</p>
          <h1>کجا سرمایه‌گذاری کنم؟</h1>
          <p className="tagline">دادهٔ انس و دلار آزاد، پیش‌بینی، و مقایسهٔ روش‌های سرمایه‌گذاری — لوکال</p>
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

      {flash ? (
        <div className={`banner ${flash.kind}`} role="status">
          <span>{flash.text}</span>
          <button type="button" className="banner-close" onClick={() => setFlash(null)} aria-label="بستن">
            ×
          </button>
        </div>
      ) : null}
      {loading && flash?.kind !== 'info' ? <div className="banner info">در حال پردازش...</div> : null}

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
          <h2>مرحله ۲ — احساس و افق پیش‌بینی</h2>
          <div className="row form-grid">
            <label>
              احساس نمودار طلا (−۱۰ تا ۱۰)
              <input
                type="number"
                min={-10}
                max={10}
                step={1}
                value={goldSentiment}
                onChange={(e) => setGoldSentiment(Number(e.target.value))}
              />
            </label>
            <label>
              احساس نمودار دلار (−۱۰ تا ۱۰)
              <input
                type="number"
                min={-10}
                max={10}
                step={1}
                value={usdSentiment}
                onChange={(e) => setUsdSentiment(Number(e.target.value))}
              />
            </label>
            <label>
              افق (ماه)
              <input
                type="number"
                min={1}
                max={36}
                value={months}
                onChange={(e) => setMonths(Number(e.target.value))}
              />
            </label>
          </div>
          <div className="row">
            <button type="button" className="primary" onClick={runForecast} disabled={loading || !dataReady}>
              اجرای پیش‌بینی (LightGBM + Prophet)
            </button>
          </div>
        </section>
      )}

      {step === 2 && forecast && (
        <section className="panel">
          <h2>مرحله ۳ — واقعی در برابر پیش‌بینی</h2>
          <p className="muted">
            مدل طلا: {forecast.gold.model_used} | مدل دلار: {forecast.usd.model_used}
          </p>
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
            <button type="button" className="primary" onClick={confirmAndContinue}>
              تایید و ادامه
            </button>
            <button type="button" className="ghost" onClick={() => setStep(1)}>
              ترین مجدد با ورودی متفاوت
            </button>
            <button type="button" className="ghost" onClick={() => setStep(0)}>
              برگشت به چارت
            </button>
          </div>
        </section>
      )}

      {step === 3 && (
        <section className="panel">
          <h2>مرحله ۴ — مدل‌های سرمایه‌گذاری</h2>
          <p className="muted">
            سه روش (فین‌تک، خرید مستقیم، بانک→وام) × طلا / دلار / صندوق. بودجه ماهانه برای مقایسه عادلانه مشترک است.
          </p>

          <h3 className="subhead">مشترک</h3>
          <div className="row form-grid">
            <label>
              سرمایه اولیه (تومان)
              <input
                type="number"
                value={capital}
                onChange={(e) => {
                  setCapital(Number(e.target.value))
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
              <input
                type="number"
                value={monthlyBudget}
                onChange={(e) => {
                  setMonthlyBudget(Number(e.target.value))
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
                <input
                  type="number"
                  value={loanAmount}
                  onChange={(e) => {
                    setLoanAmount(Number(e.target.value))
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
            <div className="row form-grid">
              <label>
                تومان به ازای هر امتیاز
                <input type="number" value={tomanPerPoint} onChange={(e) => setTomanPerPoint(Number(e.target.value))} />
              </label>
              <label>
                وام به ازای هر امتیاز
                <input type="number" value={loanPerPoint} onChange={(e) => setLoanPerPoint(Number(e.target.value))} />
              </label>
              <label>
                ماه انتظار تا وام
                <input
                  type="number"
                  value={waitMonths}
                  onChange={(e) => {
                    setWaitMonths(Number(e.target.value))
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
          )}

          <div className="row">
            <button type="button" className="primary" onClick={runInvest} disabled={loading || !budgetConfirmed}>
              محاسبه و مقایسه سود
            </button>
          </div>
        </section>
      )}

      {step === 4 && invest && (
        <section className="panel">
          <h2>مرحله ۵ — مقایسه سود</h2>
          {invest.recommendation && (
            <div className="recommend">
              <p className="recommend-label">توصیه</p>
              <p className="recommend-msg">{invest.recommendation.message}</p>
            </div>
          )}
          <table className="results">
            <thead>
              <tr>
                <th>روش / دارایی</th>
                <th>قابل سرمایه‌گذاری</th>
                <th>پایان</th>
                <th>سود خالص</th>
                <th>درصد</th>
                <th>یادداشت</th>
              </tr>
            </thead>
            <tbody>
              {invest.results.map((r) => (
                <tr
                  key={r.method}
                  className={`${r.method === invest.best_method ? 'best' : ''} ${r.valid ? '' : 'invalid'}`}
                >
                  <td>{r.title}</td>
                  <td>{r.investable.toLocaleString('fa-IR')}</td>
                  <td>{r.end_value.toLocaleString('fa-IR')}</td>
                  <td>{r.net_profit.toLocaleString('fa-IR')}</td>
                  <td>{r.profit_pct.toFixed(2)}%</td>
                  <td>{r.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row">
            <button type="button" className="ghost" onClick={() => setStep(3)}>
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
