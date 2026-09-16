import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import StatusBadge from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders a dash for null values", () => {
    render(<StatusBadge value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders the value with underscores replaced by spaces", () => {
    render(<StatusBadge value="faq_only" />);
    expect(screen.getByText("faq only")).toBeInTheDocument();
  });
});
