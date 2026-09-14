import { create } from 'zustand';
import type { DashboardPayload, ScenarioId } from '../types/domain';
import type { BackendSpillAnalysisResponse } from '../services/api';

type State = {
  // Existing demo state
  scenario: ScenarioId;
  selectedFeature: string | null;
  selectedVessel: string | null;
  layers: Record<string, boolean>;
  visualMode: 'enhanced' | 'classic';

  // Real analysis state
  analysisResult: DashboardPayload | null;
  analysisLoading: boolean;
  analysisError: string | null;
  _rawBackendResponse: BackendSpillAnalysisResponse | null;

  // Actions — existing
  setScenario: (s: ScenarioId) => void;
  selectFeature: (s: string | null) => void;
  selectVessel: (s: string | null) => void;
  setVisualMode: (mode: 'enhanced' | 'classic') => void;
  toggleLayer: (s: string) => void;

  // Actions — real analysis
  setAnalysisResult: (result: DashboardPayload | null, raw?: BackendSpillAnalysisResponse | null) => void;
  setAnalysisLoading: (loading: boolean) => void;
  setAnalysisError: (error: string | null) => void;
  clearAnalysis: () => void;
};

export const useUiStore = create<State>((set) => ({
  // Existing defaults
  scenario: 'full',
  selectedFeature: null,
  selectedVessel: null,
  visualMode: 'enhanced',
  layers: {
    'sar-footprint': true, spill: true, centroid: true, 'origin-zone': true,
    origin: true, hindcast: true, forecast: true, 'forecast-region': true,
    ais: true, vessels: true,
  },

  // Real analysis defaults
  analysisResult: null,
  analysisLoading: false,
  analysisError: null,
  _rawBackendResponse: null,

  // Existing actions
  setScenario: (scenario) => set({ scenario }),
  selectFeature: (selectedFeature) => set({ selectedFeature }),
  selectVessel: (selectedVessel) => set({ selectedVessel }),
  setVisualMode: (visualMode) => set({ visualMode }),
  toggleLayer: (key) => set((state) => ({ layers: { ...state.layers, [key]: !state.layers[key] } })),

  // Real analysis actions
  setAnalysisResult: (analysisResult, raw) => set({ analysisResult, analysisError: null, _rawBackendResponse: raw ?? null }),
  setAnalysisLoading: (analysisLoading) => set({ analysisLoading }),
  setAnalysisError: (analysisError) => set({ analysisError, analysisLoading: false }),
  clearAnalysis: () => set({ analysisResult: null, analysisError: null, analysisLoading: false, _rawBackendResponse: null }),
}));
