<!-- id: momentum-volatility version: 1.0.0 tags: ema rsi macd atr vwap momentum volatility expansion contraction -->

# Momentum, volatility and indicators

EMA alignment describes the location of price relative to smoothed averages. EMA9
above EMA21 above EMA50 is a bullish stack; the inverse is bearish. Alignment is a
description of the recent path, not a forecast.

RSI is a bounded momentum oscillator. A high RSI means recent gains dominate; it does
not by itself mean a reversal is due. RSI change is often more informative than the
absolute level.

MACD is the difference between fast and slow EMAs, with a signal EMA. A positive
histogram means MACD is above its signal. Histogram acceleration and deceleration
describe momentum change, not direction alone.

ATR measures the average true range over a window. It is used to size buffers and
distance, not to predict direction. A stop placed at a fixed ATR multiple adapts to
normal noise.

VWAP is a volume-weighted average price. Without reliable volume, VWAP is unavailable
and must not be invented.

Volatility expansion means recent ranges are larger than their recent baseline;
contraction is the reverse. High volatility widens stops and increases slippage risk.
Low volatility can precede expansion but does not predict its direction.
