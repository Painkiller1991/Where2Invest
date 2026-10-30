const BASE = ''

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = j.detail || JSON.stringify(j)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export type Candle = {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number | null
}

export type SeriesPayload = {
  symbol: string
  title: string
  unit: string
  candles: Candle[]
  source: string
  start_date: string
  end_date: string
}

export type DataStatus = {
  ready: boolean
  gold: SeriesPayload | null
  usd: SeriesPayload | null
  error: string | null
  attempts: number
  effective_start: string | null
  updated?: 'cache' | 'incremental' | 'full' | null
}

export type ForecastPoint = { time: number; value: number; is_forecast: boolean }

export type ForecastSeries = {
  symbol: string
  unit: string
  historical: Candle[]
  forecast: ForecastPoint[]
  model_used: string
  metrics: Record<string, number>
}

export type ForecastResponse = {
  gold: ForecastSeries
  usd: ForecastSeries
  months: number
  gold_sentiment: number
  usd_sentiment: number
  confirmed: boolean
}

export type InvestInput = {
  capital_toman: number
  monthly_budget_toman: number
  fund_annual_pct?: number
  enable_gold?: boolean
  enable_usd?: boolean
  enable_fund?: boolean
  enable_fintech?: boolean
  enable_direct?: boolean
  enable_bank_to_bank?: boolean
  enable_bank_to_asset?: boolean
  loan_amount?: number
  company_fee_pct?: number
  bank_annual_pct?: number
  repay_months?: number
  fee_source?: 'from_loan' | 'cash'
  toman_per_point?: number
  points_for_loan?: number
  loan_for_points?: number
  model3_bank_annual_pct?: number
  repay_months_model3?: number | null
}

export type InvestMonthStep = {
  month: number
  label: string
  events: string[]
  cash_in: number
  buy: number
  installment: number
  points: number
  deposit: number
  debt: number
  asset_value: number
  cash: number
  wealth: number
  price: number
  units_bought: number
  units_held: number
  unit_label: string
}

export type InvestResult = {
  method: string
  model: string
  asset: string
  title: string
  investable: number
  start_value: number
  end_value: number
  net_profit: number
  profit: number
  profit_pct: number
  notes: string
  valid: boolean
  timeline?: InvestMonthStep[]
  units_held?: number
  unit_label?: string
  end_price?: number
}

export type InvestRecommendation = {
  model: string
  asset: string
  method: string
  net_profit: number
  profit_pct: number
  message: string
}

export type InvestContext = {
  horizon_months: number
  usd_now: number
  usd_end: number
  usd_change_pct: number
  ounce_now: number
  ounce_end: number
  ounce_change_pct: number
  gram18_now: number
  gram18_end: number
  gram18_change_pct: number
  capital_toman: number
  monthly_budget_toman: number
  total_cash_in: number
  capital_as_usd_now: number
  capital_as_gram18_now: number
  monthly_as_usd_now: number
  monthly_as_gram18_now: number
  capital_as_usd_end: number
  capital_as_gram18_end: number
  monthly_as_usd_end: number
  monthly_as_gram18_end: number
}

export type InvestCompareResponse = {
  results: InvestResult[]
  best_method: string
  recommendation: InvestRecommendation | null
  assumptions: Record<string, unknown>
  suggested_monthly: number
  context?: InvestContext | null
}

export type InvestSuggestResponse = {
  suggested_monthly: number
  details: Record<string, number>
}

export const api = {
  getConfig: () => req<Record<string, unknown>>('/api/config'),
  putConfig: (patch: Record<string, unknown>) =>
    req<Record<string, unknown>>('/api/config', {
      method: 'PUT',
      body: JSON.stringify({ patch }),
    }),
  dataStatus: () => req<DataStatus>('/api/data/status'),
  fetchData: (start_date?: string, force = false) =>
    req<DataStatus>('/api/data/fetch', {
      method: 'POST',
      body: JSON.stringify({ start_date: start_date || null, force }),
    }),
  forecast: (body: {
    gold_sentiment: number
    usd_sentiment: number
    months: number
    model?: 'hybrid' | 'auto' | 'lightgbm' | 'prophet' | 'both' | 'drift'
  }) =>
    req<ForecastResponse>('/api/forecast', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  confirmForecast: (confirm = true) =>
    req<ForecastResponse>('/api/forecast/confirm', {
      method: 'POST',
      body: JSON.stringify({ confirm }),
    }),
  investSuggestMonthly: (body: InvestInput) =>
    req<InvestSuggestResponse>('/api/invest/suggest-monthly', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  investCompare: (body: InvestInput) =>
    req<InvestCompareResponse>('/api/invest/compare', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  userState: () => req<UserStateResponse>('/api/user/state'),
  userSavePrefs: (prefs: Record<string, unknown>) =>
    req<UserStateResponse>('/api/user/prefs', {
      method: 'PUT',
      body: JSON.stringify({ prefs }),
    }),
  userSaveChartTf: (chart_tf: '1D' | '1W' | '1M') =>
    req<UserStateResponse>('/api/user/chart-tf', {
      method: 'PUT',
      body: JSON.stringify({ chart_tf }),
    }),
  userSetActiveDecision: (active_decision_id: string | null) =>
    req<UserStateResponse>('/api/user/active-decision', {
      method: 'PUT',
      body: JSON.stringify({ active_decision_id }),
    }),
  userUpsertDecision: (decision: Record<string, unknown>) =>
    req<UserStateResponse>('/api/user/decisions', {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),
  userPatchDecision: (id: string, patch: { title?: string; note?: string }) =>
    req<UserStateResponse>(`/api/user/decisions/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  userDeleteDecision: (id: string) =>
    req<UserStateResponse>(`/api/user/decisions/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  userImport: (body: {
    prefs?: Record<string, unknown> | null
    chart_tf?: '1D' | '1W' | '1M' | null
    active_decision_id?: string | null
    decisions?: unknown[] | null
    only_if_empty?: boolean
  }) =>
    req<UserStateResponse>('/api/user/import', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
}

export type UserStateResponse = {
  prefs: Record<string, unknown>
  has_prefs: boolean
  chart_tf: '1D' | '1W' | '1M'
  active_decision_id: string | null
  decisions: Record<string, unknown>[]
}
