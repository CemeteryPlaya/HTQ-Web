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
  // Дефолты действуют, ПОКА ответ реестра не пришёл (или если запрос упал).
  // Раньше `conference` тут стоял в false — наследие тех времён, когда SFU не
  // был подключён. Из-за этого рабочая функция выглядела отключённой до
  // первого ответа, а при упавшем запросе — навсегда. Источник правды —
  // реестр на бэкенде; если сервис действительно выключен, придёт 503
  // `service_disabled`, и его перехватит ServiceUnavailableListener.
  it("все сервисы включены по умолчанию, включая конференцию", () => {
    for (const [name, enabled] of Object.entries(DEFAULT_SERVICE_STATUSES)) {
      expect(enabled, `сервис ${name} не должен быть выключен локальным дефолтом`).toBe(true);
    }
    expect(DEFAULT_SERVICE_STATUSES.conference).toBe(true);
  });
});
