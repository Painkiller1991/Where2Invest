/** اسنپ‌شات تصمیم خرید — ذخیره در SQLite از طریق API */

import type { ForecastPoint, ForecastResponse, InvestCompareResponse } from './api'
import { buildGram18Series } from './gram18'

export type DecisionSeriesSnap = {
  unit: string
  model_used: string
  last_time: number
  last_close: number
  forecast: ForecastPoint[]
}

export type DecisionSnapshot = {
  id: string
  created_at: number
  title: string
  note: string
  months: number
  gold_sentiment: number
  usd_sentiment: number
  forecast_model: string
  gold: DecisionSeriesSnap
  usd: DecisionSeriesSnap
  gram18: DecisionSeriesSnap
  invest?: {
    capital_toman: number
    monthly_budget_toman: number
    best_method: string
    recommendation: string
    net_profit?: number
    profit_pct?: number
  }
}

function seriesSnap(
  unit: string,
  model_used: string,
  histClose: number,
  histTime: number,
  forecast: ForecastPoint[],
): DecisionSeriesSnap {
  return {
    unit,
    model_used,
    last_time: histTime,
    last_close: histClose,
    forecast: forecast.map((p) => ({ time: p.time, value: p.value, is_forecast: true })),
  }
}

export function buildDecisionFromForecast(
  fc: ForecastResponse,
  opts: {
    title?: string
    note?: string
    forecastModel: string
    invest?: DecisionSnapshot['invest']
  },
): DecisionSnapshot {
  const goldLast = fc.gold.historical.at(-1)
  const usdLast = fc.usd.historical.at(-1)
  const g18 = buildGram18Series(fc.gold, fc.usd)
  const g18Last = g18.historical.at(-1)
  const when = new Date()
  const autoTitle =
    opts.title?.trim() ||
    `تصمیم ${when.toLocaleDateString('fa-IR')} — گرم۱۸ ${Math.round(g18Last?.close || 0).toLocaleString('fa-IR')}`

  return {
    id: `d_${when.getTime()}_${Math.random().toString(36).slice(2, 8)}`,
    created_at: when.getTime(),
    title: autoTitle,
    note: opts.note?.trim() || '',
    months: fc.months,
    gold_sentiment: fc.gold_sentiment,
    usd_sentiment: fc.usd_sentiment,
    forecast_model: opts.forecastModel,
    gold: seriesSnap(
      fc.gold.unit,
      fc.gold.model_used,
      goldLast?.close ?? 0,
      goldLast?.time ?? 0,
      fc.gold.forecast,
    ),
    usd: seriesSnap(
      fc.usd.unit,
      fc.usd.model_used,
      usdLast?.close ?? 0,
      usdLast?.time ?? 0,
      fc.usd.forecast,
    ),
    gram18: seriesSnap(
      'toman',
      g18.model_used,
      g18Last?.close ?? 0,
      g18Last?.time ?? 0,
      g18.forecast,
    ),
    invest: opts.invest,
  }
}

export function investSummary(res: InvestCompareResponse, capital: number, monthly: number): DecisionSnapshot['invest'] {
  const rec = res.recommendation
  return {
    capital_toman: capital,
    monthly_budget_toman: monthly,
    best_method: rec?.method || res.best_method || '',
    recommendation: rec?.message || '',
    net_profit: rec?.net_profit,
    profit_pct: rec?.profit_pct,
  }
}

export function normalizeDecision(raw: unknown): DecisionSnapshot | null {
  if (!raw || typeof raw !== 'object') return null
  const d = raw as DecisionSnapshot
  if (typeof d.id !== 'string' || !d.gold || !d.usd) return null
  return d
}

export function normalizeDecisions(list: unknown): DecisionSnapshot[] {
  if (!Array.isArray(list)) return []
  return list
    .map(normalizeDecision)
    .filter((d): d is DecisionSnapshot => Boolean(d))
    .sort((a, b) => b.created_at - a.created_at)
}
