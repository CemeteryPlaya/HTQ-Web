import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./index.css";
import "./i18n";
import { installGlobalErrorHandlers } from "./lib/telemetry";

installGlobalErrorHandlers();

createRoot(document.getElementById("root")!).render(<App />);
