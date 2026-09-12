import { dashboardScenario } from '../mock/scenarios';
import type { DashboardPayload, ScenarioId } from '../types/domain';
const pause=(ms=260)=>new Promise(resolve=>setTimeout(resolve,ms));
export const dashboardApi={ async getDashboard(scenario:ScenarioId):Promise<DashboardPayload>{ await pause(); return dashboardScenario(scenario); } };
export const incidentsApi={ async list(){ await pause(); return ['full','partial-ais','no-ais','no-environment','no-oil','processing','error'].map(s=>dashboardScenario(s as ScenarioId).incident); }, async getById(_id:string,scenario:ScenarioId){return dashboardApi.getDashboard(scenario)} };
