import { useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BrainCircuit,
  CandlestickChart,
  History,
  LayoutDashboard,
  MessagesSquare,
  PanelLeftClose,
  PanelLeftOpen,
  PlayCircle,
  Settings,
} from "lucide-react";
import { NavLink } from "react-router-dom";

import { useMarket } from "@/state/market-context";
import { cn } from "@/lib/utils";

const STORAGE_KEY = "kbmti.sidebar.collapsed";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  stage?: number;
}

const GROUPS: Array<{ label: string; items: NavItem[] }> = [
  {
    label: "Workspace",
    items: [
      { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
      { to: "/chart", label: "Market Analysis", icon: CandlestickChart },
      { to: "/signals", label: "Signal Research", icon: BrainCircuit },
      { to: "/chat", label: "AI Assistant", icon: MessagesSquare },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { to: "/history", label: "Forecasting", icon: History },
      { to: "/replay", label: "Replay", icon: PlayCircle },
    ],
  },
  {
    label: "System",
    items: [
      { to: "/settings", label: "Settings", icon: Settings },
      { to: "/diagnostics", label: "Model Status", icon: Activity },
    ],
  },
];

function RailLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const { to, label, icon: Icon, end, stage } = item;
  return (
    <NavLink
      to={to}
      end={end}
      title={collapsed ? label : undefined}
      className={({ isActive }) =>
        cn(
          "group/nav relative mx-2 flex h-[33px] items-center gap-2.5 rounded-[7px] px-2.5 text-[12px] font-medium",
          "transition-[background-color,color] duration-150 ease-out",
          collapsed ? "justify-center px-0" : "pr-2",
          isActive
            ? "bg-primary/[0.08] text-ink"
            : "text-ink-muted hover:bg-hover hover:text-ink",
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span
              className="absolute top-1/2 left-0 h-4 w-[2px] -translate-y-1/2 rounded-full bg-primary"
              aria-hidden
            />
          )}
          <Icon
            className={cn(
              "size-4 shrink-0",
              isActive ? "text-primary" : "text-ink-faint group-hover/nav:text-ink-muted",
            )}
            aria-hidden
          />
          {!collapsed && (
            <>
              <span className="truncate">{label}</span>
              {stage && (
                <span
                  className="ml-auto rounded-[4px] border border-line bg-surface-2 px-1 text-[8.5px] leading-[13px] font-medium text-ink-faint"
                  title={`Reserved for Stage ${stage}`}
                >
                  S{stage}
                </span>
              )}
            </>
          )}
          {collapsed && <span className="rail-tooltip">{label}</span>}
        </>
      )}
    </NavLink>
  );
}

export function Sidebar() {
  const { stream, settingsError } = useMarket();
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem(STORAGE_KEY) === "1";
    } catch {
      return false;
    }
  });

  const toggle = () => {
    setCollapsed((previous) => {
      const next = !previous;
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {
        // Storage is optional; the rail still collapses for this session.
      }
      return next;
    });
  };

  const connected = stream.status?.connected ?? false;
  const transport = stream.transport;
  const providerLabel = stream.status?.provider_label ?? "Market feed";

  return (
    <aside
      className={cn(
        "relative flex shrink-0 flex-col border-r border-line bg-rail text-ink transition-[width] duration-150",
        collapsed ? "w-[64px]" : "w-[220px]",
      )}
    >
      <div
        className={cn(
          "flex h-[56px] shrink-0 items-center gap-2.5 border-b border-line",
          collapsed ? "justify-center px-0" : "px-3.5",
        )}
      >
        <img
          src="/brand/icon.svg"
          alt="KBMTI"
          width={32}
          height={32}
          className={cn("shrink-0 rounded-[8px]", collapsed ? "size-8" : "size-8")}
        />
        {!collapsed && (
          <div className="min-w-0 leading-none">
            <p className="text-[13px] font-semibold tracking-[0.12em] text-ink">KBMTI</p>
            <p className="mt-1 truncate text-[8.5px] font-medium tracking-[0.01em] text-ink-faint">
              BTC Market Intelligence
            </p>
          </div>
        )}
      </div>

      <nav aria-label="Primary" className="min-h-0 flex-1 overflow-visible py-2">
        {GROUPS.map((group) => (
          <div key={group.label} className="pb-1.5">
            {!collapsed ? (
              <p className="px-4 pt-3 pb-1.5 text-[9.5px] font-medium tracking-[0.01em] text-ink-faint">
                {group.label}
              </p>
            ) : (
              <div className="mx-3 my-2 h-px bg-line" />
            )}
            {group.items.map((item) => (
              <RailLink key={item.to} item={item} collapsed={collapsed} />
            ))}
          </div>
        ))}
      </nav>

      <div className="shrink-0 border-t border-line px-2 py-2">
        {collapsed ? (
          <div
            className="grid h-7 place-items-center"
            title={`${providerLabel} ${connected ? "connected" : "offline"}`}
          >
            <span
              className={cn(
                "size-2 rounded-full",
                connected ? "bg-bull" : transport === "open" ? "bg-warn" : "bg-line-strong",
              )}
            />
          </div>
        ) : (
          <div className="rounded-[8px] border border-line-soft bg-surface px-2.5 py-2">
            <div className="flex items-center gap-1.5">
              <span
                className={cn("size-1.5 rounded-full", connected ? "bg-bull" : "bg-warn")}
              />
              <span className="text-[9.5px] font-medium text-ink-muted">{providerLabel}</span>
              <span className="ml-auto text-[9.5px] text-ink-faint">
                {connected ? "live" : "offline"}
              </span>
            </div>
            <p className="mt-1 truncate text-[9.5px] text-ink-faint">
              {settingsError ? "Settings degraded" : "Read-only market data"}
            </p>
          </div>
        )}

        <button
          type="button"
          onClick={toggle}
          aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          aria-expanded={!collapsed}
          className={cn(
            "mt-1.5 flex h-8 w-full items-center gap-2 rounded-[6px] px-2 text-[10.5px] text-ink-faint transition-colors hover:bg-hover hover:text-ink-muted",
            collapsed && "justify-center px-0",
          )}
        >
          {collapsed ? (
            <PanelLeftOpen className="size-3.5" aria-hidden />
          ) : (
            <>
              <PanelLeftClose className="size-3.5" aria-hidden />
              <span>Collapse rail</span>
              <span className="num ml-auto text-[9px] text-ink-faint/80">v1.2</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
