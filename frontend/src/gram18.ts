import type { Candle, ForecastPoint, ForecastSeries } from './api'

export const TROY_OZ = 31.1034768

export function gram18From(ounce: number, usd: number) {
  if (!(ounce > 0) || !(usd > 0)) return 0
  return ((ounce * usd) / TROY_OZ) * (18 / 24)
}

/** گرم ۱۸ عیار به تومان — قیمت ذاتی از انس جهانی × دلار آزاد (بدون اجرت). */
export function buildGram18Series(gold: ForecastSeries, usd: ForecastSeries): ForecastSeries {
  return {
    symbol: 'XAU18/IRT',
    unit: 'toman',
    historical: buildGram18Candles(gold.historical, usd.historical),
    forecast: buildGram18Forecast(gold.forecast, usd.forecast),
    model_used: `انس(${gold.model_used}) × دلار(${usd.model_used})`,
    metrics: {},
  }
}

export function buildGram18Candles(gold: Candle[], usd: Candle[]): Candle[] {
  const usdSorted = [...usd].sort((a, b) => a.time - b.time)
  let ui = 0
  let lastUsd: Candle | null = usdSorted[0] ?? null
  const historical: Candle[] = []
  for (const g of [...gold].sort((a, b) => a.time - b.time)) {
    while (ui + 1 < usdSorted.length && usdSorted[ui + 1].time <= g.time) {
      ui += 1
      lastUsd = usdSorted[ui]
    }
    if (!lastUsd) continue
    const uClose = lastUsd.close
    const uOpen = lastUsd.open > 0 ? lastUsd.open : uClose
    const close = gram18From(g.close, uClose)
    if (!(close > 0)) continue
    const open = gram18From(g.open > 0 ? g.open : g.close, uOpen)
    const hiOz = Math.max(g.open, g.high, g.low, g.close)
    const loOz = Math.min(...[g.open, g.high, g.low, g.close].filter((x) => x > 0), g.close)
    const hiUsd = Math.max(lastUsd.open, lastUsd.high, lastUsd.low, lastUsd.close)
    const loUsd = Math.min(
      ...[lastUsd.open, lastUsd.high, lastUsd.low, lastUsd.close].filter((x) => x > 0),
      uClose,
    )
    const corners = [
      open,
      close,
      gram18From(hiOz, hiUsd),
      gram18From(hiOz, loUsd),
      gram18From(loOz, hiUsd),
      gram18From(loOz, loUsd),
    ].filter((x) => x > 0)
    historical.push({
      time: g.time,
      open: open > 0 ? open : close,
      high: Math.max(...corners),
      low: Math.min(...corners),
      close,
      volume: 0,
    })
  }
  return historical
}

export function buildGram18Forecast(gold: ForecastPoint[], usd: ForecastPoint[]): ForecastPoint[] {
  const n = Math.min(gold.length, usd.length)
  const forecast: ForecastPoint[] = []
  for (let i = 0; i < n; i++) {
    const value = gram18From(gold[i].value, usd[i].value)
    if (!(value > 0)) continue
    forecast.push({ time: gold[i].time, value, is_forecast: true })
  }
  return forecast
}
