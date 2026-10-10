import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/inter/latin-700.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// Cache only the public app shell and static assets; patient APIs always require the network.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener(
    "load",
    () =>
      void navigator.serviceWorker.register("/sw.js").catch(() => undefined),
  );
}
