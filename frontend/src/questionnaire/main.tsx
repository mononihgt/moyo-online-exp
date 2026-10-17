import React from "react";
import ReactDOM from "react-dom/client";

import QuestionnaireApp from "./QuestionnaireApp";
import "../styles/tokens.css";
import "../styles/questionnaire.css";

ReactDOM.createRoot(document.getElementById("questionnaire-root")!).render(
  <React.StrictMode>
    <QuestionnaireApp />
  </React.StrictMode>,
);
