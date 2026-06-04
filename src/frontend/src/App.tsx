import { Routes, Route } from "react-router-dom";
import Layout from "./Layout";
import StatusBoard from "./pages/StatusBoard";
import PipelineDetail from "./pages/PipelineDetail";
import TraceExplorer from "./pages/TraceExplorer";
import Telemetry from "./pages/Telemetry";
import Provenance from "./pages/Provenance";
import SBOMViewer from "./pages/SBOMViewer";
import VulnerabilityDashboard from "./pages/VulnerabilityDashboard";
import ProvenanceDiff from "./pages/ProvenanceDiff";
import Admin from "./pages/Admin";
import Artifacts from "./pages/Artifacts";
import Collector from "./pages/Collector";
import Hallucinations from "./pages/Hallucinations";
import TracesPage from "./pages/Traces";

function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<StatusBoard />} />
        <Route path="/pipelines/:slug" element={<PipelineDetail />} />
        <Route path="/pipelines/:slug/diff" element={<ProvenanceDiff />} />
        <Route path="/traces/:runId" element={<TraceExplorer />} />
        <Route path="/artifacts" element={<Artifacts />} />
        <Route path="/telemetry" element={<Telemetry />} />
        <Route path="/provenance" element={<Provenance />} />
        <Route path="/sboms/:digest" element={<SBOMViewer />} />
        <Route path="/vulnerabilities" element={<VulnerabilityDashboard />} />
        <Route path="/hallucinations" element={<Hallucinations />} />
        <Route path="/agent-traces" element={<TracesPage />} />
        <Route path="/collector" element={<Collector />} />
        <Route path="/admin" element={<Admin />} />
      </Route>
    </Routes>
  );
}

export default App;
