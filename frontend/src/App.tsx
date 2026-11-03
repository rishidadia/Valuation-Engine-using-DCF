import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Landing from "./pages/Landing";
import DataPage from "./pages/DataPage";
import AssumptionsPage from "./pages/AssumptionsPage";
import ForecastPage from "./pages/ForecastPage";
import WaccPage from "./pages/WaccPage";
import FcfPage from "./pages/FcfPage";
import DcfPage from "./pages/DcfPage";
import SensitivityPage from "./pages/SensitivityPage";
import ScenariosPage from "./pages/ScenariosPage";
import ComparablesPage from "./pages/ComparablesPage";
import AuditPage from "./pages/AuditPage";
import ReportPage from "./pages/ReportPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/workspace" element={<Layout />}>
        <Route index element={<Navigate to="/workspace/data" replace />} />
        <Route path="data" element={<DataPage />} />
        <Route path="assumptions" element={<AssumptionsPage />} />
        <Route path="forecast" element={<ForecastPage />} />
        <Route path="wacc" element={<WaccPage />} />
        <Route path="fcf" element={<FcfPage />} />
        <Route path="dcf" element={<DcfPage />} />
        <Route path="sensitivity" element={<SensitivityPage />} />
        <Route path="scenarios" element={<ScenariosPage />} />
        <Route path="comparables" element={<ComparablesPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="report" element={<ReportPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
