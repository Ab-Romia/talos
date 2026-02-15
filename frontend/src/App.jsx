import { useState } from "react";
import ChatPage from "./page/ChatPage/ChatPage";
import { Routes, Route } from "react-router-dom";
import * as PageRoutes from "./constants/Routes.js";

function App() {
  return (
    <>
      <Routes>
        <Route path={PageRoutes.HOME_URL} element={<h1>Landing Page</h1>} />
        <Route path={PageRoutes.CHAT_PAGE} element={<ChatPage />} />
        <Route path={PageRoutes.TEST_PAGE} element={<h1>TESTING ROUTES</h1>} />
        <Route path="*" element={<h1>Invalid Route</h1>} />
      </Routes>
    </>
  );
}

export default App;
