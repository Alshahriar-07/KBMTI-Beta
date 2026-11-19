export type SignalTone = "success" | "danger" | "warning" | "neutral";

export function signalTone(label: string | undefined): SignalTone {
  if (label === "BUY BIAS") return "success";
  if (label === "SELL BIAS") return "danger";
  if (label === "WAIT") return "warning";
  return "neutral";
}
