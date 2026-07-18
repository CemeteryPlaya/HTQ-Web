import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ServiceUnavailableDialog } from "../ServiceUnavailableDialog";
import { DEFAULT_SERVICE_STATUSES } from "@/hooks/useServiceStatus";

describe("ServiceUnavailableDialog", () => {
  it("показывает сообщение о недоступности", () => {
    render(<ServiceUnavailableDialog service="conference" open onOpenChange={() => {}} />);
    expect(screen.getByText(/недоступен/i)).toBeInTheDocument();
  });
});

describe("useServiceStatus defaults", () => {
  it("конференция выключена по умолчанию (SFU не задействован)", () => {
    expect(DEFAULT_SERVICE_STATUSES.conference).toBe(false);
  });
});
