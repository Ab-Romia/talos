import { useState } from "react";
import ChatPage from "./page/ChatPage/ChatPage";
import { Routes, Route } from "react-router-dom";

function App() {
  return (
    <>
      <Routes>
        <Route path="/" element={<h1>Landing Page to be added</h1>} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/test" element={<h1>TESTING ROUTES</h1>} />
        <Route path="*" element={<h1>Invalid Route</h1>} />
      </Routes>
    </>
  );
}

export default App;
