/** Prefs types + defaults. Persistence is SQLite via /api/user/* (not browser). */

export const LEGACY_FORM_KEY = 'where2invest:form-v1'
export const LEGACY_CHART_TF_KEY = 'where2invest:chart-tf'

export type ForecastModel = 'hybrid' | 'auto' | 'lightgbm' | 'prophet' | 'both' | 'drift'

export type FormPrefs = {
  startDate: string
  goldSentiment: number
  usdSentiment: number
  months: number
  forecastModel: ForecastModel
  capital: number
  monthlyBudget: number
  fundAnnual: number
  enableGold: boolean
  enableUsd: boolean
  enableFund: boolean
  enableFintech: boolean
  enableDirect: boolean
  enableBankToBank: boolean
  enableBankToAsset: boolean
  loanAmount: number
  companyFeePct: number
  bankAnnualPct: number
  repayMonths: number
  feeSource: 'from_loan' | 'cash'
  tomanPerPoint: number
  pointsForLoan: number
  loanForPoints: number
  model3BankAnnual: number
}

export const FORM_DEFAULTS: FormPrefs = {
  startDate: '2018-01-01',
  goldSentiment: 0,
  usdSentiment: 0,
  months: 3,
  forecastModel: 'both',
  capital: 100_000_000,
  monthlyBudget: 0,
  fundAnnual: 20,
  enableGold: true,
  enableUsd: true,
  enableFund: true,
  enableFintech: true,
  enableDirect: true,
  enableBankToBank: true,
  enableBankToAsset: true,
  loanAmount: 100_000_000,
  companyFeePct: 5,
  bankAnnualPct: 22,
  repayMonths: 12,
  feeSource: 'from_loan',
  tomanPerPoint: 100_000,
  pointsForLoan: 100,
  loanForPoints: 100_000_000,
  model3BankAnnual: 0,
}

const FORECAST_MODELS: ForecastModel[] = [
  'hybrid',
  'auto',
  'lightgbm',
  'prophet',
  'both',
  'drift',
]

function asNumber(v: unknown, fallback: number): number {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : fallback
}

function asBool(v: unknown, fallback: boolean): boolean {
  return typeof v === 'boolean' ? v : fallback
}

function asString(v: unknown, fallback: string): string {
  return typeof v === 'string' && v.length > 0 ? v : fallback
}

export function normalizeFormPrefs(raw: Partial<FormPrefs> | Record<string, unknown> | null | undefined): FormPrefs {
  const d = FORM_DEFAULTS
  const p = (raw || {}) as Partial<FormPrefs>
  const model = FORECAST_MODELS.includes(p.forecastModel as ForecastModel)
    ? (p.forecastModel as ForecastModel)
    : d.forecastModel
  const fee = p.feeSource === 'cash' || p.feeSource === 'from_loan' ? p.feeSource : d.feeSource
  return {
    startDate: asString(p.startDate, d.startDate),
    goldSentiment: asNumber(p.goldSentiment, d.goldSentiment),
    usdSentiment: asNumber(p.usdSentiment, d.usdSentiment),
    months: Math.min(36, Math.max(1, Math.round(asNumber(p.months, d.months)))),
    forecastModel: model,
    capital: asNumber(p.capital, d.capital),
    monthlyBudget: asNumber(p.monthlyBudget, d.monthlyBudget),
    fundAnnual: asNumber(p.fundAnnual, d.fundAnnual),
    enableGold: asBool(p.enableGold, d.enableGold),
    enableUsd: asBool(p.enableUsd, d.enableUsd),
    enableFund: asBool(p.enableFund, d.enableFund),
    enableFintech: asBool(p.enableFintech, d.enableFintech),
    enableDirect: asBool(p.enableDirect, d.enableDirect),
    enableBankToBank: asBool(p.enableBankToBank, d.enableBankToBank),
    enableBankToAsset: asBool(p.enableBankToAsset, d.enableBankToAsset),
    loanAmount: asNumber(p.loanAmount, d.loanAmount),
    companyFeePct: asNumber(p.companyFeePct, d.companyFeePct),
    bankAnnualPct: asNumber(p.bankAnnualPct, d.bankAnnualPct),
    repayMonths: Math.max(1, Math.round(asNumber(p.repayMonths, d.repayMonths))),
    feeSource: fee,
    tomanPerPoint: asNumber(p.tomanPerPoint, d.tomanPerPoint),
    pointsForLoan: asNumber(p.pointsForLoan, d.pointsForLoan),
    loanForPoints: asNumber(p.loanForPoints, d.loanForPoints),
    model3BankAnnual: asNumber(p.model3BankAnnual, d.model3BankAnnual),
  }
}

export type ChartTf = '1D' | '1W' | '1M'

export function normalizeChartTf(v: unknown, fallback: ChartTf = '1W'): ChartTf {
  return v === '1D' || v === '1W' || v === '1M' ? v : fallback
}

/** Peek legacy browser keys once for DB import, then caller should clear. */
export function peekLegacyBrowserBundle(): {
  prefs: FormPrefs | null
  chart_tf: ChartTf | null
  active_decision_id: string | null
  decisions: unknown[] | null
} {
  try {
    const prefsRaw = localStorage.getItem(LEGACY_FORM_KEY)
    const tfRaw = localStorage.getItem(LEGACY_CHART_TF_KEY)
    const active = localStorage.getItem('where2invest:active-decision')
    const decRaw = localStorage.getItem('where2invest:decisions-v1')
    return {
      prefs: prefsRaw ? normalizeFormPrefs(JSON.parse(prefsRaw)) : null,
      chart_tf: tfRaw ? normalizeChartTf(tfRaw, '1W') : null,
      active_decision_id: active,
      decisions: decRaw ? (JSON.parse(decRaw) as unknown[]) : null,
    }
  } catch {
    return { prefs: null, chart_tf: null, active_decision_id: null, decisions: null }
  }
}

export function clearLegacyBrowserKeys(): void {
  try {
    localStorage.removeItem(LEGACY_FORM_KEY)
    localStorage.removeItem(LEGACY_CHART_TF_KEY)
    localStorage.removeItem('where2invest:active-decision')
    localStorage.removeItem('where2invest:decisions-v1')
    localStorage.removeItem('where2invest:migrated-to-db')
  } catch {
    /* ignore */
  }
}

export function markLegacyMigrated(): void {
  try {
    localStorage.setItem('where2invest:migrated-to-db', '1')
  } catch {
    /* ignore */
  }
}

export function wasLegacyMigrated(): boolean {
  try {
    return localStorage.getItem('where2invest:migrated-to-db') === '1'
  } catch {
    return false
  }
}
