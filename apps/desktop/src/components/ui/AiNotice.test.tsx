import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AiNotice } from "@/components/ui/AiNotice";

describe("AiNotice", () => {
  it("states that PATRON output is active and not financial advice", () => {
    render(<AiNotice />);
    expect(screen.getByText("PATRON model intelligence is active")).toBeInTheDocument();
    expect(screen.getByText(/trained PATRON model/i)).toBeInTheDocument();
    expect(screen.getByText(/financial advice/i)).toBeInTheDocument();
  });
});
