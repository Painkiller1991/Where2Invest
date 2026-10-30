import { useEffect, useMemo, useRef, useState } from 'react'
import {
  dispose,
  getSupportedOverlays,
  init,
  registerOverlay,
  type Chart,
  type KLineData,
} from 'klinecharts'
import { api, type Candle, type ForecastPoint } from '../api'
import { normalizeChartTf, type ChartTf } from '../persist'

type Tf = ChartTf

export type DecisionOverlay = {
  label: string
  /** unix seconds */
  decisionTime: number
  decisionPrice: number
  /** مسیر پیش‌بینی ذخیره‌شده (unix seconds) */
  points: { time: number; value: number }[]
  color?: string
}

const DECISION_COLOR = '#7c4dff'
const REAL_LEGEND = '#26a69a'

let decisionOverlayRegistered = false
function ensureDecisionPathOverlay() {
  if (decisionOverlayRegistered) return
  decisionOverlayRegistered = true
  try {
    registerOverlay({
      name: 'decisionPath',
      totalStep: 1,
      needDefaultPointFigure: false,
      needDefaultXAxisFigure: false,
      needDefaultYAxisFigure: false,
      createPointFigures: ({ coordinates }) => {
        if (!coordinates || coordinates.length < 2) return []
        return [
          {
            type: 'line',
            attrs: { coordinates },
            styles: { style: 'solid', size: 2.5 },
          },
        ]
      },
    })
  } catch {
    /* already registered / unsupported */
  }
}

const TOOLS: { name: string; label: string }[] = [
  { name: 'segment', label: '/' },
  { name: 'straightLine', label: '／' },
  { name: 'rayLine', label: '↗' },
  { name: 'horizontalStraightLine', label: '─' },
  { name: 'horizontalRayLine', label: '→' },
  { name: 'verticalStraightLine', label: '│' },
  { name: 'priceLine', label: 'P' },
  { name: 'priceChannelLine', label: '∥' },
  { name: 'parallelStraightLine', label: '//' },
  { name: 'fibonacciLine', label: 'Fib' },
  { name: 'fibonacciExtension', label: 'Ext' },
  { name: 'rect', label: '▭' },
  { name: 'circle', label: '○' },
  { name: 'triangle', label: '△' },
  { name: 'arrow', label: '➤' },
]

type Props = {
  title: string
  symbol?: string
  unit: string
  candles: Candle[]
  forecast?: ForecastPoint[]
  /** مسیر تصمیم خرید ذخیره‌شده روی چارت واقعی */
  decisionOverlay?: DecisionOverlay | null
  /** تایم‌فریم مشترک از دیتابیس؛ اگر نباشد خودش لود/ذخیره می‌کند */
  timeframe?: ChartTf
  onTimeframeChange?: (tf: ChartTf) => void
  height?: number
}

function toKLine(candles: Candle[]): KLineData[] {
  return candles.map((c) => ({
    timestamp: c.time * 1000,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
    volume: c.volume ?? 0,
  }))
}

function mergeForecast(candles: Candle[], forecast?: ForecastPoint[]): KLineData[] {
  const base = toKLine(candles)
  if (!forecast?.length) return base
  const lastClose = candles[candles.length - 1]?.close ?? forecast[0].value
  let prev = lastClose
  for (const p of forecast) {
    const v = p.value
    base.push({
      timestamp: p.time * 1000,
      open: prev,
      high: Math.max(prev, v),
      low: Math.min(prev, v),
      close: v,
      volume: 0,
      forecast: true,
    } as KLineData)
    prev = v
  }
  return base
}

function weekKey(ts: number): string {
  const d = new Date(ts)
  // ISO-like week: Thursday-based year + week number
  const tmp = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()))
  const day = tmp.getUTCDay() || 7
  tmp.setUTCDate(tmp.getUTCDate() + 4 - day)
  const yearStart = new Date(Date.UTC(tmp.getUTCFullYear(), 0, 1))
  const week = Math.ceil(((tmp.getTime() - yearStart.getTime()) / 86400000 + 1) / 7)
  return `${tmp.getUTCFullYear()}-W${week}`
}

function monthKey(ts: number): string {
  const d = new Date(ts)
  return `${d.getUTCFullYear()}-${d.getUTCMonth() + 1}`
}

function aggregate(data: KLineData[], tf: Tf): KLineData[] {
  if (tf === '1D' || data.length === 0) return data
  const out: KLineData[] = []
  let bucket: KLineData | null = null
  let bucketKey = ''
  for (const bar of data) {
    const key = tf === '1W' ? weekKey(bar.timestamp) : monthKey(bar.timestamp)
    if (!bucket || key !== bucketKey) {
      if (bucket) out.push(bucket)
      bucket = { ...bar }
      bucketKey = key
    } else {
      bucket.high = Math.max(bucket.high, bar.high)
      bucket.low = Math.min(bucket.low, bar.low)
      bucket.close = bar.close
      bucket.volume = (bucket.volume ?? 0) + (bar.volume ?? 0)
    }
  }
  if (bucket) out.push(bucket)
  return out
}

function fmt(n: number, digits = 2) {
  return n.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: 0 })
}

const LIGHT_STYLES = {
  grid: {
    horizontal: { color: '#e8e8e8' },
    vertical: { color: '#e8e8e8' },
  },
  candle: {
    type: 'candle_solid' as const,
    bar: {
      upColor: '#26a69a',
      downColor: '#ef5350',
      upBorderColor: '#26a69a',
      downBorderColor: '#ef5350',
      upWickColor: '#26a69a',
      downWickColor: '#ef5350',
    },
    priceMark: {
      last: {
        show: true,
        upColor: '#2962ff',
        downColor: '#2962ff',
        noChangeColor: '#2962ff',
      },
    },
    tooltip: { showRule: 'always' as const },
  },
  xAxis: {
    axisLine: { color: '#d0d0d0' },
    tickText: { color: '#666' },
  },
  yAxis: {
    axisLine: { color: '#d0d0d0' },
    tickText: { color: '#666' },
  },
  crosshair: {
    horizontal: { line: { color: '#999' } },
    vertical: { line: { color: '#999' } },
  },
}

const FONT_STEPS = [11, 12, 13, 14, 16, 18, 20]

function axisFontStyles(size: number) {
  return {
    xAxis: { tickText: { size, color: '#666', family: 'Vazirmatn, Tahoma, sans-serif' } },
    yAxis: { tickText: { size, color: '#666', family: 'Vazirmatn, Tahoma, sans-serif' } },
    candle: {
      tooltip: {
        text: { size: size + 1, family: 'Vazirmatn, Tahoma, sans-serif' },
      },
    },
  }
}

export default function TradeChart({
  title,
  symbol,
  unit,
  candles,
  forecast,
  decisionOverlay = null,
  timeframe,
  onTimeframeChange,
  height = 540,
}: Props) {
  const rootRef = useRef<HTMLElement | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<Chart | null>(null)
  const dataRef = useRef<KLineData[]>([])
  const drawIdsRef = useRef<string[]>([])
  const [tf, setTfState] = useState<Tf>(() => normalizeChartTf(timeframe, '1W'))
  const setTf = (t: Tf) => {
    setTfState(t)
    onTimeframeChange?.(t)
    if (!onTimeframeChange) {
      void api.userSaveChartTf(t).catch(() => undefined)
    }
  }

  useEffect(() => {
    if (timeframe) setTfState(normalizeChartTf(timeframe, '1W'))
  }, [timeframe])
  const [activeTool, setActiveTool] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [drawCount, setDrawCount] = useState(0)
  const [ohlc, setOhlc] = useState<{ o: number; h: number; l: number; c: number } | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [fontSize, setFontSize] = useState(13)

  const ticker = symbol || title

  const syncDrawCount = () => setDrawCount(drawIdsRef.current.length)

  const applyFont = (chart: Chart, size: number) => {
    chart.setStyles(axisFontStyles(size) as never)
  }

  const overlays = useMemo(() => {
    try {
      const supported = getSupportedOverlays()
      return TOOLS.filter((t) => supported.includes(t.name))
    } catch {
      return TOOLS
    }
  }, [])

  const baseDaily = useMemo(() => mergeForecast(candles, forecast), [candles, forecast])

  useEffect(() => {
    if (!containerRef.current) return
    ensureDecisionPathOverlay()
    const chart = init(containerRef.current, {
      timezone: 'Asia/Tehran',
      styles: { ...LIGHT_STYLES, ...axisFontStyles(fontSize) } as never,
    })
    if (!chart) return
    chartRef.current = chart

    const precision = unit.includes('USD') || unit.includes('oz') ? 2 : 0
    chart.setSymbol({ ticker, pricePrecision: precision, volumePrecision: 0 })
    chart.setPeriod({ type: 'day', span: 1 })

    const data = aggregate(baseDaily, tf)
    dataRef.current = data
    if (data.length) {
      const last = data[data.length - 1]
      setOhlc({ o: last.open, h: last.high, l: last.low, c: last.close })
    }

    chart.setDataLoader({
      getBars: ({ callback }) => {
        callback(dataRef.current, { backward: false, forward: false })
      },
    })

    chart.subscribeAction('onCrosshairChange', (data) => {
      const k = (data as { kLineData?: KLineData }).kLineData
      if (k) setOhlc({ o: k.open, h: k.high, l: k.low, c: k.close })
    })

    drawIdsRef.current = []
    setSelectedId(null)
    setDrawCount(0)

    if (forecast?.length && candles.length) {
      const splitTs = candles[candles.length - 1].time * 1000
      try {
        chart.createOverlay({
          name: 'verticalStraightLine',
          id: 'forecast-split',
          points: [{ timestamp: splitTs, value: candles[candles.length - 1].close }],
          styles: { line: { color: '#f57c00', size: 1, style: 'dashed' } },
          lock: true,
        })
      } catch {
        /* ignore */
      }
    }

    if (decisionOverlay && decisionOverlay.points.length > 0) {
      const color = decisionOverlay.color || DECISION_COLOR
      const path = [
        { timestamp: decisionOverlay.decisionTime * 1000, value: decisionOverlay.decisionPrice },
        ...decisionOverlay.points.map((p) => ({ timestamp: p.time * 1000, value: p.value })),
      ]
      try {
        chart.createOverlay({
          name: 'decisionPath',
          id: 'decision-path',
          points: path,
          lock: true,
          styles: { line: { color, size: 2.5 } },
        })
      } catch {
        // fallback: تکه‌خطوط
        for (let i = 0; i < path.length - 1; i++) {
          try {
            chart.createOverlay({
              name: 'segment',
              id: `decision-seg-${i}`,
              points: [path[i], path[i + 1]],
              lock: true,
              styles: { line: { color, size: 2 } },
            })
          } catch {
            /* ignore */
          }
        }
      }
      try {
        chart.createOverlay({
          name: 'verticalStraightLine',
          id: 'decision-split',
          points: [{ timestamp: decisionOverlay.decisionTime * 1000, value: decisionOverlay.decisionPrice }],
          styles: { line: { color, size: 1, style: 'dashed' } },
          lock: true,
        })
      } catch {
        /* ignore */
      }
    }

    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      dispose(chart)
      chartRef.current = null
    }
    // fontSize applied separately so drawings are not wiped on font change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, unit, baseDaily, tf, forecast, candles, decisionOverlay])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    applyFont(chart, fontSize)
    // toolbar width also scales with font; wait a frame then resize canvas
    requestAnimationFrame(() => chart.resize())
  }, [fontSize])

  useEffect(() => {
    const onFs = () => {
      const el = rootRef.current
      const active = Boolean(document.fullscreenElement && el && document.fullscreenElement === el)
      setFullscreen(active)
      requestAnimationFrame(() => chartRef.current?.resize())
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && fullscreen && !document.fullscreenElement) {
        setFullscreen(false)
        requestAnimationFrame(() => chartRef.current?.resize())
      }
    }
    document.addEventListener('fullscreenchange', onFs)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('fullscreenchange', onFs)
      document.removeEventListener('keydown', onKey)
    }
  }, [fullscreen])

  const toggleFullscreen = async () => {
    const el = rootRef.current
    if (!el) return
    try {
      if (!document.fullscreenElement) {
        await el.requestFullscreen()
      } else if (document.fullscreenElement === el) {
        await document.exitFullscreen()
      } else {
        await document.exitFullscreen()
        await el.requestFullscreen()
      }
    } catch {
      // CSS fallback if Fullscreen API blocked
      setFullscreen((v) => !v)
      requestAnimationFrame(() => chartRef.current?.resize())
    }
  }

  const bumpFont = (dir: 1 | -1) => {
    setFontSize((cur) => {
      const i = FONT_STEPS.findIndex((s) => s >= cur)
      const idx = i < 0 ? 0 : i
      const next = FONT_STEPS[Math.min(FONT_STEPS.length - 1, Math.max(0, idx + dir))]
      return next
    })
  }

  const trackOverlay = (id: string | null | undefined) => {
    if (!id || id === 'forecast-split') return
    if (!drawIdsRef.current.includes(id)) {
      drawIdsRef.current = [...drawIdsRef.current, id]
      syncDrawCount()
    }
    setSelectedId(id)
  }

  const startDraw = (name: string) => {
    const chart = chartRef.current
    if (!chart) return
    setActiveTool(name)
    const id = chart.createOverlay({
      name,
      onDrawEnd: (event) => {
        trackOverlay(event.overlay.id)
        setActiveTool(null)
      },
      onSelected: (event) => {
        const oid = event.overlay.id
        if (oid && oid !== 'forecast-split') setSelectedId(oid)
      },
      onDeselected: () => setSelectedId(null),
      onRemoved: (event) => {
        const oid = event.overlay.id
        if (!oid) return
        drawIdsRef.current = drawIdsRef.current.filter((x) => x !== oid)
        syncDrawCount()
        setSelectedId((cur) => (cur === oid ? null : cur))
      },
    })
    // Some overlays resolve id immediately; final id also arrives in onDrawEnd
    if (typeof id === 'string') trackOverlay(id)
  }

  const undoLast = () => {
    const chart = chartRef.current
    const ids = drawIdsRef.current
    if (!chart || ids.length === 0) return
    const last = ids[ids.length - 1]
    chart.removeOverlay({ id: last })
    drawIdsRef.current = ids.slice(0, -1)
    syncDrawCount()
    setSelectedId((cur) => (cur === last ? null : cur))
    setActiveTool(null)
  }

  const deleteSelected = () => {
    const chart = chartRef.current
    if (!chart) return
    const target = selectedId || drawIdsRef.current[drawIdsRef.current.length - 1]
    if (!target) return
    chart.removeOverlay({ id: target })
    drawIdsRef.current = drawIdsRef.current.filter((x) => x !== target)
    syncDrawCount()
    setSelectedId(null)
    setActiveTool(null)
  }

  const clearDrawings = () => {
    const chart = chartRef.current
    if (!chart) return
    for (const id of [...drawIdsRef.current]) {
      chart.removeOverlay({ id })
    }
    drawIdsRef.current = []
    syncDrawCount()
    setSelectedId(null)
    setActiveTool(null)
  }

  const changeUp = ohlc ? ohlc.c >= ohlc.o : true
  const hasForecast = Boolean(forecast?.length && candles.length)
  const hasDecision = Boolean(decisionOverlay?.points?.length)

  const canvasHeight = fullscreen ? 'calc(100vh - 56px)' : height

  return (
    <section
      ref={rootRef}
      className={`pro-chart ${fullscreen ? 'is-fullscreen' : ''}`}
      style={{ ['--pro-font-size' as string]: `${fontSize}px` }}
    >
      <div className="pro-chart-top" dir="ltr">
        <div className="pro-symbol">
          <strong>{ticker}</strong>
          <span className="pro-tf-tag">{tf}</span>
          <span className="pro-title-fa" dir="rtl">
            {title}
          </span>
        </div>
        <div className="pro-tf-group">
          {(['1D', '1W', '1M'] as Tf[]).map((t) => (
            <button
              key={t}
              type="button"
              className={`pro-tf ${tf === t ? 'active' : ''}`}
              onClick={() => setTf(t)}
            >
              {t}
            </button>
          ))}
        </div>
        {ohlc ? (
          <div className={`pro-ohlc ${changeUp ? 'up' : 'down'}`}>
            <span>
              O <b>{fmt(ohlc.o)}</b>
            </span>
            <span>
              H <b>{fmt(ohlc.h)}</b>
            </span>
            <span>
              L <b>{fmt(ohlc.l)}</b>
            </span>
            <span>
              C <b>{fmt(ohlc.c)}</b>
            </span>
            <span className="pro-unit">{unit}</span>
          </div>
        ) : null}
        {hasForecast || hasDecision ? (
          <div className="pro-legend" dir="rtl">
            <span className="dot real" style={{ background: REAL_LEGEND }} /> واقعی
            {hasForecast ? (
              <>
                <span className="dot pred" /> پیش‌بینی جاری
              </>
            ) : null}
            {hasDecision ? (
              <>
                <span
                  className="dot decision"
                  style={{ background: decisionOverlay?.color || DECISION_COLOR }}
                />
                تصمیم: {decisionOverlay?.label}
              </>
            ) : null}
          </div>
        ) : null}
        <div className="pro-view-controls">
          <button type="button" className="pro-view-btn" title="فونت کوچکتر" onClick={() => bumpFont(-1)}>
            A−
          </button>
          <span className="pro-font-label">{fontSize}</span>
          <button type="button" className="pro-view-btn" title="فونت بزرگتر" onClick={() => bumpFont(1)}>
            A+
          </button>
          <button
            type="button"
            className="pro-view-btn"
            title={fullscreen ? 'خروج از تمام‌صفحه (Esc)' : 'تمام‌صفحه'}
            onClick={toggleFullscreen}
          >
            {fullscreen ? '⛶' : '⛶'}
            <span className="pro-view-btn-text">{fullscreen ? 'Exit' : 'Full'}</span>
          </button>
        </div>
      </div>

      <div className="pro-chart-body">
        <aside className="pro-tools" dir="ltr">
          {overlays.map((t) => (
            <button
              key={t.name}
              type="button"
              className={`pro-tool ${activeTool === t.name ? 'active' : ''}`}
              title={t.name}
              onClick={() => startDraw(t.name)}
            >
              {t.label}
            </button>
          ))}
          <button
            type="button"
            className="pro-tool"
            title="برگشت یک مرحله (Undo)"
            onClick={undoLast}
            disabled={drawCount === 0}
          >
            ↩
          </button>
          <button
            type="button"
            className={`pro-tool ${selectedId ? 'active' : ''}`}
            title={selectedId ? 'حذف خط انتخاب‌شده' : 'حذف آخرین خط'}
            onClick={deleteSelected}
            disabled={drawCount === 0}
          >
            ⌫
          </button>
          <button
            type="button"
            className="pro-tool danger"
            title="پاک کردن همه خطوط"
            onClick={clearDrawings}
            disabled={drawCount === 0}
          >
            ✕
          </button>
        </aside>
        <div
          ref={containerRef}
          className="pro-canvas"
          style={{ height: canvasHeight }}
        />
      </div>
    </section>
  )
}
