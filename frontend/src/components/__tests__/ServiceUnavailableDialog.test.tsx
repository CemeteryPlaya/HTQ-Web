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
  it("до ответа реестра сервисы считаются включёнными, включая конференцию", () => {
    // Раньше conference был выключен по умолчанию — пока SFU не был поднят.
    // Теперь стек в строю (миграция core/0003), и прежний дефолт показывал
    // «Функция временно отключена» на каждой заминке с ответом реестра.
    expect(Object.values(DEFAULT_SERVICE_STATUSES).every(Boolean)).toBe(true);
    expect(DEFAULT_SERVICE_STATUSES.conference).toBe(true);
  });
});
