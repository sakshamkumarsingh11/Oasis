import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { LandingPage, DashboardPage, IncidentsPage, CreateIncidentPage, MapPage, VesselPage, ReportPage } from './pages/Pages';
import { SpillLabPage } from './pages/SpillLabPage';
export function App(){return <BrowserRouter><Routes><Route path="/" element={<LandingPage/>}/><Route path="/dashboard" element={<DashboardPage/>}/><Route path="/incidents" element={<IncidentsPage/>}/><Route path="/create" element={<CreateIncidentPage/>}/><Route path="/map" element={<MapPage/>}/><Route path="/vessels" element={<VesselPage/>}/><Route path="/report" element={<ReportPage/>}/><Route path="/spill-lab" element={<SpillLabPage/>}/><Route path="*" element={<DashboardPage/>}/></Routes></BrowserRouter>}
