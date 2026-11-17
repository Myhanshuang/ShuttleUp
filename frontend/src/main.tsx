import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { SessionProvider } from "./session";
import { FeedbackProvider } from "./ui";
import "./styles/base.css";
createRoot(document.getElementById("app")!).render(
  <BrowserRouter>
    <FeedbackProvider>
      <SessionProvider>
        <App />
      </SessionProvider>
    </FeedbackProvider>
  </BrowserRouter>,
);
