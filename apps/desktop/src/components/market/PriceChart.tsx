import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type ISeriesPrimitive,
  type IPrimitivePaneView,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import type { CanvasRenderingTarget2D } from "fancy-canvas";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Theme } from "@/lib/theme";
import type {
  OverlayBand,
  OverlayTone,
  TradeChartOverlay,
} from "@/lib/trade-visual";
import type { Candle, ChartSettings, Indicators } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useTheme } from "@/state/theme-context";

interface PriceChartProps {
  candles: Candle[];
  forming: Candle | null;
  indicators: Indicators | null;
  chart: ChartSettings;
  digits: number;
  symbol: string;
  timeframe: string;
  source?: string;
  height?: number | string;
  className?: string;
  fitVersion?: number;
  overlay?: TradeChartOverlay | null;
}

interface HoverCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface ChartPalette {
  bull: string;
  bear: string;
  ema9: string;
  ema21: string;
  ema50: string;
  band: string;
  bandMiddle: string;
  rsi: string;
  macd: string;
  macdSignal: string;
  grid: string;
  border: string;
  text: string;
  crosshair: string;
  priceLine: string;
  label: string;
  panelHover: string;
  upVolume: string;
  downVolume: string;
  upHistogram: string;
  downHistogram: string;
}

const OVERLAY_COLORS: Record<Theme, Record<OverlayTone, string>> = {
  dark: {
    entry: "rgba(77,154,255,0.95)",
    risk: "rgba(228,107,112,0.9)",
    target: "rgba(53,183,121,0.95)",
    confirmation: "rgba(216,168,93,0.9)",
    support: "rgba(53,183,121,0.72)",
    resistance: "rgba(228,107,112,0.72)",
    liquidity: "rgba(216,168,93,0.72)",
    forecast: "rgba(77,154,255,0.8)",
    scenario: "rgba(176,186,197,0.72)",
  },
  light: {
    entry: "rgba(47,111,219,0.95)",
    risk: "rgba(214,69,80,0.9)",
    target: "rgba(22,134,83,0.95)",
    confirmation: "rgba(169,107,23,0.9)",
    support: "rgba(22,134,83,0.72)",
    resistance: "rgba(214,69,80,0.72)",
    liquidity: "rgba(169,107,23,0.72)",
    forecast: "rgba(47,111,219,0.8)",
    scenario: "rgba(89,99,111,0.72)",
  },
};

const BAND_FILL: Record<OverlayBand["tone"], string> = {
  entry: "rgba(77,154,255,0.10)",
  risk: "rgba(228,107,112,0.10)",
  reward: "rgba(53,183,121,0.07)",
  forecast: "rgba(77,154,255,0.06)",
};

const BAND_BORDER: Record<OverlayBand["tone"], string> = {
  entry: "rgba(77,154,255,0.55)",
  risk: "rgba(228,107,112,0.55)",
  reward: "rgba(53,183,121,0.45)",
  forecast: "rgba(77,154,255,0.4)",
};

/**
 * Draws full-width translucent bands behind the candles. The primitive uses the
 * series' own price scale, so the zones remain aligned while zooming, panning and
 * resizing; no pixel positions are cached from a previous viewport.
 */
class BandPrimitive implements ISeriesPrimitive<Time> {
  private readonly series: ISeriesApi<"Candlestick">;
  private readonly bands: OverlayBand[];

  constructor(series: ISeriesApi<"Candlestick">, bands: OverlayBand[]) {
    this.series = series;
    this.bands = bands;
  }

  private readonly view: IPrimitivePaneView = {
    zOrder: () => "bottom",
    renderer: () => ({
      draw: (target: CanvasRenderingTarget2D) => {
        if (!this.bands.length) return;
        target.useMediaCoordinateSpace((scope) => {
          const context = scope.context;
          for (const band of this.bands) {
            const top = this.series.priceToCoordinate(Math.max(band.lower, band.upper));
            const bottom = this.series.priceToCoordinate(Math.min(band.lower, band.upper));
            if (top === null || bottom === null || bottom <= top) continue;
            context.fillStyle = BAND_FILL[band.tone];
            context.fillRect(0, top, scope.mediaSize.width, bottom - top);
            context.strokeStyle = BAND_BORDER[band.tone];
            context.lineWidth = 1;
            context.setLineDash([3, 3]);
            context.beginPath();
            context.moveTo(0, top);
            context.lineTo(scope.mediaSize.width, top);
            context.moveTo(0, bottom);
            context.lineTo(scope.mediaSize.width, bottom);
            context.stroke();
            context.setLineDash([]);
            if (bottom - top > 16) {
              context.fillStyle = "rgba(180,190,200,0.72)";
              context.font = '9px "Inter", "Segoe UI", system-ui, sans-serif';
              context.fillText(band.label, 7, top + 11);
            }
          }
        });
      },
    }),
  };

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }
}

const CHART_PALETTES: Record<Theme, ChartPalette> = {
  dark: {
    bull: "#35b779",
    bear: "#e46b70",
    ema9: "#4d9aff",
    ema21: "#8cbcff",
    ema50: "#a0a8b1",
    band: "rgba(77,154,255,0.34)",
    bandMiddle: "rgba(77,154,255,0.16)",
    rsi: "#4d9aff",
    macd: "#4d9aff",
    macdSignal: "#d8a85d",
    grid: "rgba(255,255,255,0.032)",
    border: "#292f35",
    text: "#8a939d",
    crosshair: "rgba(77,154,255,0.32)",
    priceLine: "rgba(160,168,177,0.24)",
    label: "#2f7bff",
    panelHover: "rgba(77,154,255,0.35)",
    upVolume: "rgba(53,183,121,0.24)",
    downVolume: "rgba(228,107,112,0.22)",
    upHistogram: "rgba(53,183,121,0.4)",
    downHistogram: "rgba(228,107,112,0.36)",
  },
  light: {
    bull: "#168653",
    bear: "#d64550",
    ema9: "#2f6fdb",
    ema21: "#5b8def",
    ema50: "#59636f",
    band: "rgba(47,111,219,0.22)",
    bandMiddle: "rgba(47,111,219,0.11)",
    rsi: "#2f6fdb",
    macd: "#2f6fdb",
    macdSignal: "#a96b17",
    grid: "rgba(23,27,32,0.045)",
    border: "#e2e7ed",
    text: "#5f6b77",
    crosshair: "rgba(47,111,219,0.32)",
    priceLine: "rgba(89,99,111,0.28)",
    label: "#1f5bc4",
    panelHover: "rgba(47,111,219,0.3)",
    upVolume: "rgba(22,134,83,0.24)",
    downVolume: "rgba(214,69,80,0.22)",
    upHistogram: "rgba(22,134,83,0.4)",
    downHistogram: "rgba(214,69,80,0.36)",
  },
};

function lineData(points: Array<{ time: number; value: number }> | undefined) {
  return (points ?? []).map((point) => ({
    time: point.time as UTCTimestamp,
    value: point.value,
  }));
}

function brokerStamp(epochSeconds: number): string {
  const iso = new Date(epochSeconds * 1000).toISOString();
  return `${iso.slice(0, 16).replace("T", " ")} UTC`;
}

export function PriceChart({
  candles,
  forming,
  indicators,
  chart: chartOptions,
  digits,
  symbol,
  timeframe,
  source = "market",
  height = "100%",
  className,
  fitVersion = 0,
  overlay = null,
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const emaRefs = useRef<Array<ISeriesApi<"Line"> | null>>([null, null, null]);
  const bandRefs = useRef<Array<ISeriesApi<"Line"> | null>>([null, null, null]);
  const rsiRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdSignalRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdHistRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const overlayLinesRef = useRef<IPriceLine[]>([]);
  const overlayMarkersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const overlayPathsRef = useRef<Array<ISeriesApi<"Line">>>([]);
  const overlayPredictedRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const overlayBandRef = useRef<BandPrimitive | null>(null);
  const previousKeyRef = useRef<string>("");
  const chartRenderRef = useRef<{
    length: number;
    firstTime: number;
    lastTime: number;
    indicators: Indicators | null;
  } | null>(null);
  const [hovered, setHovered] = useState<HoverCandle | null>(null);
  const { theme } = useTheme();
  const COLORS = CHART_PALETTES[theme];
  const sourceLabel = source === "binance" ? "Binance" : source === "mt5" ? "MetaTrader 5" : source;

  const merged = useMemo(() => {
    const map = new Map<number, Candle>();
    for (const candle of candles) map.set(candle.time, candle);
    if (forming) map.set(forming.time, forming);
    return [...map.values()].sort((a, b) => a.time - b.time);
  }, [candles, forming]);

  // The chart instance is rebuilt when layers change; read the latest data from a
  // ref so that rebuild can repopulate the series immediately.
  const dataRef = useRef({ merged, indicators });
  dataRef.current = { merged, indicators };

  const last = hovered ?? (merged.length ? merged[merged.length - 1] : null);
  const change = last ? last.close - last.open : null;
  const latest = indicators?.latest ?? {};

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const chart = createChart(element, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        attributionLogo: false,
        textColor: COLORS.text,
        fontSize: 10.5,
        fontFamily: '"Inter", "Segoe UI", system-ui, sans-serif',
        panes: {
          separatorColor: COLORS.border,
          separatorHoverColor: COLORS.panelHover,
          enableResize: true,
        },
      },
      grid: {
        vertLines: { color: COLORS.grid },
        horzLines: { color: COLORS.grid },
      },
      rightPriceScale: {
        borderColor: COLORS.border,
        scaleMargins: { top: 0.06, bottom: chartOptions.show_volume ? 0.22 : 0.06 },
      },
      timeScale: {
        borderColor: COLORS.border,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 6,
        barSpacing: 8,
        minBarSpacing: 2.5,
      },
      crosshair: {
        mode: chartOptions.crosshair ? CrosshairMode.Magnet : CrosshairMode.Normal,
        vertLine: {
          color: COLORS.crosshair,
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: COLORS.label,
        },
        horzLine: {
          color: COLORS.crosshair,
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: COLORS.label,
        },
      },
      localization: {
        priceFormatter: (price: number) => price.toFixed(digits),
      },
    });

    chartRef.current = chart;
    const priceFormat = { type: "price" as const, precision: digits, minMove: 10 ** -digits };
    const candlesSeries = chart.addSeries(CandlestickSeries, {
      upColor: COLORS.bull,
      downColor: COLORS.bear,
      wickUpColor: COLORS.bull,
      wickDownColor: COLORS.bear,
      borderVisible: false,
      priceFormat,
      priceLineVisible: true,
      priceLineColor: COLORS.priceLine,
      priceLineWidth: 1,
      priceLineStyle: LineStyle.Dotted,
      lastValueVisible: true,
    });
    candleRef.current = candlesSeries;

    if (chartOptions.show_volume) {
      const volume = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
        priceLineVisible: false,
        lastValueVisible: false,
      });
      chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      volumeRef.current = volume;
    }

    if (chartOptions.show_ema) {
      emaRefs.current = [COLORS.ema9, COLORS.ema21, COLORS.ema50].map((color) =>
        chart.addSeries(LineSeries, {
          color,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        }),
      );
    }

    if (chartOptions.show_bollinger) {
      bandRefs.current = [COLORS.band, COLORS.bandMiddle, COLORS.band].map((color) =>
        chart.addSeries(LineSeries, {
          color,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        }),
      );
    }

    if (chartOptions.show_rsi) {
      const rsi = chart.addSeries(
        LineSeries,
        {
          color: COLORS.rsi,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: false,
          autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
        },
        1,
      );
      rsi.createPriceLine({
        price: 70,
        color: COLORS.downVolume,
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: "70",
      });
      rsi.createPriceLine({
        price: 30,
        color: COLORS.upVolume,
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: "30",
      });
      rsiRef.current = rsi;
    }

    if (chartOptions.show_macd) {
      const pane = chartOptions.show_rsi ? 2 : 1;
      const histogram = chart.addSeries(
        HistogramSeries,
        {
          priceLineVisible: false,
          lastValueVisible: false,
          priceFormat: { type: "price", precision: 2, minMove: 0.01 },
        },
        pane,
      );
      const macd = chart.addSeries(
        LineSeries,
        {
          color: COLORS.macd,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        },
        pane,
      );
      const signal = chart.addSeries(
        LineSeries,
        {
          color: COLORS.macdSignal,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        },
        pane,
      );
      macdHistRef.current = histogram;
      macdRef.current = macd;
      macdSignalRef.current = signal;
    }

    const panes = chart.panes();
    if (panes.length > 1) panes[1].setHeight(92);
    if (panes.length > 2) panes[2].setHeight(92);

    // Seed the freshly built chart before the crosshair subscription.
    const seed = dataRef.current;
    if (seed.merged.length) {
      candlesSeries.setData(
        seed.merged.map((candle) => ({
          time: candle.time as UTCTimestamp,
          open: candle.open,
          high: candle.high,
          low: candle.low,
          close: candle.close,
        })),
      );
      volumeRef.current?.setData(
        seed.merged.map((candle) => ({
          time: candle.time as UTCTimestamp,
          value: candle.tick_volume,
          color:
            candle.close >= candle.open ? COLORS.upVolume : COLORS.downVolume,
        })),
      );
      const series = seed.indicators?.series;
      emaRefs.current[0]?.setData(lineData(series?.ema9));
      emaRefs.current[1]?.setData(lineData(series?.ema21));
      emaRefs.current[2]?.setData(lineData(series?.ema50));
      bandRefs.current[0]?.setData(lineData(series?.bbUpper));
      bandRefs.current[1]?.setData(lineData(series?.bbMiddle));
      bandRefs.current[2]?.setData(lineData(series?.bbLower));
      rsiRef.current?.setData(lineData(series?.rsi14));
      macdRef.current?.setData(lineData(series?.macd));
      macdSignalRef.current?.setData(lineData(series?.macdSignal));
      macdHistRef.current?.setData(
        (series?.macdHistogram ?? []).map((point) => ({
          time: point.time as UTCTimestamp,
          value: point.value,
          color: point.value >= 0 ? COLORS.upHistogram : COLORS.downHistogram,
        })),
      );
      chart.timeScale().fitContent();
      chartRenderRef.current = {
        length: seed.merged.length,
        firstTime: seed.merged[0]?.time ?? 0,
        lastTime: seed.merged[seed.merged.length - 1]?.time ?? 0,
        indicators: seed.indicators,
      };
    }

    const onCrosshair = (param: MouseEventParams) => {
      const series = candleRef.current;
      if (!param.time || !series) {
        setHovered(null);
        return;
      }
      const data = param.seriesData.get(series) as
        | { open: number; high: number; low: number; close: number }
        | undefined;
      if (!data) {
        setHovered(null);
        return;
      }
      setHovered({
        time: Number(param.time),
        open: data.open,
        high: data.high,
        low: data.low,
        close: data.close,
      });
    };
    chart.subscribeCrosshairMove(onCrosshair);

    return () => {
      chart.unsubscribeCrosshairMove(onCrosshair);
      overlayMarkersRef.current?.detach();
      overlayMarkersRef.current = null;
      overlayLinesRef.current = [];
      overlayPathsRef.current = [];
      overlayPredictedRef.current = null;
      overlayBandRef.current = null;
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      emaRefs.current = [null, null, null];
      bandRefs.current = [null, null, null];
      rsiRef.current = null;
      macdRef.current = null;
      macdSignalRef.current = null;
      macdHistRef.current = null;
      setHovered(null);
    };
  }, [
    chartOptions.crosshair,
    chartOptions.show_bollinger,
    chartOptions.show_ema,
    chartOptions.show_macd,
    chartOptions.show_rsi,
    chartOptions.show_volume,
    digits,
    COLORS,
  ]);

  useEffect(() => {
    const series = candleRef.current;
    if (!series) return;
    const last = merged[merged.length - 1];
    const previous = chartRenderRef.current;
    const fastUpdate =
      previous !== null &&
      last !== undefined &&
      previous.indicators === indicators &&
      merged.length >= previous.length &&
      merged.length - previous.length <= 1 &&
      (merged[0]?.time ?? 0) === previous.firstTime &&
      last.time >= previous.lastTime;
    if (fastUpdate) {
      // Forming-candle ticks and a single confirmed close only touch the last
      // bar; avoid replacing 500 candles and every indicator on each frame.
      series.update({
        time: last.time as UTCTimestamp,
        open: last.open,
        high: last.high,
        low: last.low,
        close: last.close,
      });
      volumeRef.current?.update({
        time: last.time as UTCTimestamp,
        value: last.tick_volume,
        color: last.close >= last.open ? COLORS.upVolume : COLORS.downVolume,
      });
      chartRenderRef.current = {
        length: merged.length,
        firstTime: merged[0]?.time ?? 0,
        lastTime: last.time,
        indicators,
      };
      return;
    }

    series.setData(
      merged.map((candle) => ({
        time: candle.time as UTCTimestamp,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    );

    volumeRef.current?.setData(
      merged.map((candle) => ({
        time: candle.time as UTCTimestamp,
        value: candle.tick_volume,
        color: candle.close >= candle.open ? COLORS.upVolume : COLORS.downVolume,
      })),
    );

    const indicatorSeries = indicators?.series;
    emaRefs.current[0]?.setData(lineData(indicatorSeries?.ema9));
    emaRefs.current[1]?.setData(lineData(indicatorSeries?.ema21));
    emaRefs.current[2]?.setData(lineData(indicatorSeries?.ema50));
    bandRefs.current[0]?.setData(lineData(indicatorSeries?.bbUpper));
    bandRefs.current[1]?.setData(lineData(indicatorSeries?.bbMiddle));
    bandRefs.current[2]?.setData(lineData(indicatorSeries?.bbLower));
    rsiRef.current?.setData(lineData(indicatorSeries?.rsi14));
    macdRef.current?.setData(lineData(indicatorSeries?.macd));
    macdSignalRef.current?.setData(lineData(indicatorSeries?.macdSignal));
    macdHistRef.current?.setData(
      (indicatorSeries?.macdHistogram ?? []).map((point) => ({
        time: point.time as UTCTimestamp,
        value: point.value,
        color: point.value >= 0 ? COLORS.upHistogram : COLORS.downHistogram,
      })),
    );
    chartRenderRef.current = {
      length: merged.length,
      firstTime: merged[0]?.time ?? 0,
      lastTime: merged[merged.length - 1]?.time ?? 0,
      indicators,
    };

    const key = `${symbol}:${timeframe}`;
    if (previousKeyRef.current !== key) {
      previousKeyRef.current = key;
      const frame = window.requestAnimationFrame(() => chartRef.current?.timeScale().fitContent());
      return () => window.cancelAnimationFrame(frame);
    }
  }, [merged, indicators, symbol, timeframe, COLORS]);

  useEffect(() => {
    if (fitVersion === 0) return;
    chartRef.current?.timeScale().fitContent();
  }, [fitVersion]);

  useEffect(() => {
    const chart = chartRef.current;
    const series = candleRef.current;
    if (!chart || !series) return;

    for (const line of overlayLinesRef.current) series.removePriceLine(line);
    overlayLinesRef.current = [];
    overlayMarkersRef.current?.detach();
    overlayMarkersRef.current = null;
    for (const pathSeries of overlayPathsRef.current) chart.removeSeries(pathSeries);
    overlayPathsRef.current = [];
    if (overlayPredictedRef.current) {
      chart.removeSeries(overlayPredictedRef.current);
      overlayPredictedRef.current = null;
    }
    if (overlayBandRef.current) {
      series.detachPrimitive(overlayBandRef.current);
      overlayBandRef.current = null;
    }
    if (!overlay) return;

    const colors = OVERLAY_COLORS[theme];
    overlayLinesRef.current = overlay.lines.map((line) =>
      series.createPriceLine({
        price: line.price,
        color: colors[line.tone],
        lineWidth: 1,
        lineStyle: line.dashed ? LineStyle.Dashed : LineStyle.Solid,
        axisLabelVisible: true,
        title: line.label,
      }),
    );

    if (overlay.bands.length) {
      const primitive = new BandPrimitive(series, overlay.bands);
      series.attachPrimitive(primitive);
      overlayBandRef.current = primitive;
    }

    if (overlay.markers.length) {
      const markers: SeriesMarker<Time>[] = overlay.markers.map((marker) => ({
        time: marker.time as UTCTimestamp,
        position:
          marker.direction === "BULLISH"
            ? "belowBar"
            : marker.direction === "BEARISH"
              ? "aboveBar"
              : "inBar",
        color:
          marker.direction === "BULLISH"
            ? COLORS.bull
            : marker.direction === "BEARISH"
              ? COLORS.bear
              : COLORS.text,
        shape:
          marker.direction === "BULLISH"
            ? "arrowUp"
            : marker.direction === "BEARISH"
              ? "arrowDown"
              : "circle",
        text: marker.label,
        size: 1,
      }));
      overlayMarkersRef.current = createSeriesMarkers(series, markers);
    }

    if (overlay.predictedCandles.length) {
      const predicted = chart.addSeries(CandlestickSeries, {
        upColor: COLORS.upVolume,
        downColor: COLORS.downVolume,
        wickUpColor: COLORS.upVolume,
        wickDownColor: COLORS.downVolume,
        borderVisible: false,
        priceLineVisible: false,
        lastValueVisible: false,
        priceFormat: { type: "price", precision: digits, minMove: 10 ** -digits },
      });
      predicted.setData(
        overlay.predictedCandles.map((candle) => ({
          time: candle.time as UTCTimestamp,
          open: candle.open,
          high: candle.high,
          low: candle.low,
          close: candle.close,
        })),
      );
      overlayPredictedRef.current = predicted;
    }

    overlayPathsRef.current = overlay.paths.map((path) => {
      const pathSeries = chart.addSeries(LineSeries, {
        color: colors[path.tone],
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: true,
        crosshairMarkerRadius: 3,
        title: path.label,
        priceFormat: { type: "price", precision: digits, minMove: 10 ** -digits },
      });
      pathSeries.setData(
        path.points.map((point) => ({
          time: point.time as UTCTimestamp,
          value: point.price,
        })),
      );
      return pathSeries;
    });
  }, [
    overlay,
    theme,
    digits,
    COLORS,
    chartOptions.crosshair,
    chartOptions.show_bollinger,
    chartOptions.show_ema,
    chartOptions.show_macd,
    chartOptions.show_rsi,
    chartOptions.show_volume,
  ]);

  return (
    <div className={cn("relative h-full min-h-0 w-full", className)}>
      <div className="pointer-events-none absolute top-0 left-0 z-10 flex flex-col gap-1 px-2 py-1.5 [text-shadow:0_1px_3px_var(--color-chart)]">
        <div className="flex items-center gap-2">
          <span className="num text-[11.5px] font-semibold text-ink">{symbol}</span>
          <span className="text-[9px] text-ink-faint">
            {timeframe} · {sourceLabel}
          </span>
          {last && (
            <span className="num text-[9px] text-ink-faint/80">{brokerStamp(last.time)}</span>
          )}
        </div>
        {last ? (
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            {[
              ["O", last.open],
              ["H", last.high],
              ["L", last.low],
            ].map(([label, value]) => (
              <span key={String(label)} className="text-[10px] text-ink-faint">
                {label}{" "}
                <span className="num text-ink-muted">{Number(value).toFixed(digits)}</span>
              </span>
            ))}
            <span className="text-[10px] text-ink-faint">
              C{" "}
              <span
                className={cn(
                  "num",
                  change === null || change === 0
                    ? "text-ink-muted"
                    : change < 0
                      ? "text-bear"
                      : "text-bull",
                )}
              >
                {last.close.toFixed(digits)}
              </span>
            </span>
            <span
              className={cn(
                "num text-[9.5px]",
                change === null || change === 0
                  ? "text-ink-faint"
                  : change < 0
                    ? "text-bear/80"
                    : "text-bull/80",
              )}
            >
              {change === null ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(digits)}`}
            </span>
          </div>
        ) : (
          <span className="text-[10px] text-ink-faint">No broker candles yet</span>
        )}
        {chartOptions.show_ema && (
          <div className="hidden items-center gap-2.5 text-[9px] md:flex">
            <span className="text-primary">
              EMA 9 <span className="num">{latest.ema9?.toFixed(digits) ?? "—"}</span>
            </span>
            <span className="text-primary-deep">
              EMA 21 <span className="num">{latest.ema21?.toFixed(digits) ?? "—"}</span>
            </span>
            <span className="text-ink-muted">
              EMA 50 <span className="num">{latest.ema50?.toFixed(digits) ?? "—"}</span>
            </span>
          </div>
        )}
      </div>

      <div ref={containerRef} style={{ height }} className="w-full" />

      {merged.length === 0 && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <div className="text-center">
            <p className="text-[11.5px] text-ink-muted">No candles loaded</p>
            <p className="mt-0.5 text-[10.5px] text-ink-faint">
              Connect a market feed to stream candle history.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
