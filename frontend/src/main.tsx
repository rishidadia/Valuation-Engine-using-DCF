import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { ValuationProvider } from "./state/ValuationContext";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ValuationProvider>
        <App />
      </ValuationProvider>
    </BrowserRouter>
  </React.StrictMode>
);
