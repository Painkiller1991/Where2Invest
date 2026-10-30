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
  loan_per_point?: number
  wait_months?: number
  model3_bank_annual_pct?: number
  repay_months_model3?: number | null
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
}

export type InvestRecommendation = {
  model: string
  asset: string
  method: string
  net_profit: number
  profit_pct: number
  message: string
}

export type InvestCompareResponse = {
  results: InvestResult[]
  best_method: string
  recommendation: InvestRecommendation | null
  assumptions: Record<string, unknown>
  suggested_monthly: number
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
    model?: string
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
}
