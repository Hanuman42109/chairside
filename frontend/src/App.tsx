import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import CallsListPage from "./pages/CallsListPage";
import EvalResultsPage from "./pages/EvalResultsPage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/calls" replace />} />
        <Route path="/calls" element={<CallsListPage />} />
        <Route path="/eval-results" element={<EvalResultsPage />} />
      </Routes>
    </Layout>
  );
}
