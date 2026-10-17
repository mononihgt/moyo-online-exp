import { Navigate, Route, Routes } from "react-router-dom";

import "./participant-extra.css";
import CompletePage from "./CompletePage";
import ConsentPage from "./ConsentPage";
import ContactPage from "./ContactPage";
import HistoryPage from "./HistoryPage";
import HomePage from "./HomePage";
import LoginPage from "./LoginPage";
import RoomPage from "./RoomPage";
import { ParticipantGuard } from "./session";

export default function ParticipantApp() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ParticipantGuard />}>
        <Route path="/consent" element={<ConsentPage />} />
        <Route path="/" element={<HomePage />} />
        <Route path="/room/:roomId" element={<RoomPage />} />
        <Route path="/complete" element={<CompletePage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/contact" element={<ContactPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
