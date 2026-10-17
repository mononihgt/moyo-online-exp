import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import AdminApp from "./admin/AdminApp";
import ParticipantApp from "./participant/ParticipantApp";
import "./styles/tokens.css";
import "./styles/participant.css";
import "./styles/experiment.css";
import "./styles/admin.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/admin/*" element={<AdminApp />} />
        <Route path="/*" element={<ParticipantApp />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
