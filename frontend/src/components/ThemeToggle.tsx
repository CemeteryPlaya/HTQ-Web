import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTheme } from "next-themes";

export const ThemeToggle = () => {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  if (!mounted) return null;

  const isDark = theme === "dark";
  const next = isDark ? "light" : "dark";

  return (
    <Button
      variant="ghost"
      size="icon"
      className="rounded-full border border-primary/30 bg-background/60 backdrop-blur-sm hover:bg-primary/10"
      onClick={() => setTheme(next)}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
    >
      {isDark ? <Sun size={18} /> : <Moon size={18} />}
    </Button>
  );
};
