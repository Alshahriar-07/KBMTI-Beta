import { HashRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { AssistantPage } from "@/pages/AssistantPage";
import { ChatPage } from "@/pages/ChatPage";
import { DiagnosticsPage } from "@/pages/DiagnosticsPage";
import { ForecastHistoryPage } from "@/pages/ForecastHistoryPage";
import { JournalPage } from "@/pages/JournalPage";
import { LearningPage } from "@/pages/LearningPage";
import { MarketChartPage } from "@/pages/MarketChartPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { OverviewPage } from "@/pages/Overview";
import { ReplayPage } from "@/pages/ReplayPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SignalsPage } from "@/pages/SignalsPage";
import { MarketProvider } from "@/state/MarketProvider";
import { ThemeProvider } from "@/state/ThemeProvider";

export function App() {
  return (
    <ThemeProvider>
      <MarketProvider>
        <HashRouter>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<OverviewPage />} />
              <Route path="chart" element={<MarketChartPage />} />
              <Route path="assistant" element={<AssistantPage />} />
              <Route path="signals" element={<SignalsPage />} />
              <Route path="journal" element={<JournalPage />} />
              <Route path="learning" element={<LearningPage />} />
              <Route path="chat" element={<ChatPage />} />
              <Route path="history" element={<ForecastHistoryPage />} />
              <Route path="replay" element={<ReplayPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="diagnostics" element={<DiagnosticsPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </HashRouter>
      </MarketProvider>
    </ThemeProvider>
  );
}
