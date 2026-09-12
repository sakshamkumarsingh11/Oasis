import { create } from 'zustand';
import type { ScenarioId } from '../types/domain';
type State={scenario:ScenarioId; selectedFeature:string|null; selectedVessel:string|null; layers:Record<string,boolean>; setScenario:(s:ScenarioId)=>void; selectFeature:(s:string|null)=>void; selectVessel:(s:string|null)=>void; toggleLayer:(s:string)=>void};
export const useUiStore = create<State>((set) => ({
  scenario: 'full', selectedFeature: null, selectedVessel: null,
  layers: { 'sar-footprint':true, spill:true, centroid:true, 'origin-zone':true, origin:true, hindcast:true, forecast:true, 'forecast-region':true, ais:true, vessels:true },
  setScenario: (scenario) => set({ scenario }),
  selectFeature: (selectedFeature) => set({ selectedFeature }),
  selectVessel: (selectedVessel) => set({ selectedVessel }),
  toggleLayer: (key) => set((state) => ({ layers: { ...state.layers, [key]: !state.layers[key] } })),
}));
