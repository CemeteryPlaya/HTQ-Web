import { useEffect } from "react";
import { useTheme } from "next-themes";
import { Toaster as Sonner, toast } from "sonner";

import { setToastHostMounted } from "@/lib/notifications/toastHost";

type ToasterProps = React.ComponentProps<typeof Sonner>;

const Toaster = ({ ...props }: ToasterProps) => {
  const { theme = "system" } = useTheme();

  // Пока этот компонент не смонтирован, любой `toast(...)` пропадает молча —
  // sonner не копит отправленное. Источники уведомлений ждут этого флага,
  // чтобы не сжечь уведомление впустую: см. lib/notifications/toastHost.ts.
  useEffect(() => {
    setToastHostMounted(true);
    return () => setToastHostMounted(false);
  }, []);

  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className="toaster group"
      // Угол задан явно, хотя он же и по умолчанию: место карточки —
      // требование к продукту, а не случайность настроек библиотеки.
      position="bottom-right"
      // Уведомления приходят пачкой (первый опрос после открытия платформы
      // приносит всё непрочитанное разом), а при штатных трёх видимых
      // остальные ждали очереди дольше, чем человек смотрит в угол экрана.
      visibleToasts={5}
      // Таймер жизни карточки не тикает, пока вкладку не смотрят. Иначе
      // уведомление, пришедшее в фоне, истекало до возвращения человека —
      // то есть звук был, а карточки он снова не видел.
      pauseWhenPageIsHidden
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-background group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg",
          description: "group-[.toast]:text-muted-foreground",
          actionButton: "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton: "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
        },
      }}
      {...props}
    />
  );
};

export { Toaster, toast };
