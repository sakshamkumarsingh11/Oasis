import { useQuery } from '@tanstack/react-query';
import { dashboardApi } from '../api/client';
import { useUiStore } from '../store/uiStore';

/**
 * Central data hook used by ALL pages.
 *
 * Priority: if a real backend analysis result is stored in Zustand,
 * return that directly. Otherwise fall back to mock scenario data.
 */
export function useDashboard() {
  const scenario = useUiStore(s => s.scenario);
  const analysisResult = useUiStore(s => s.analysisResult);

  const mockQuery = useQuery({
    queryKey: ['dashboard', scenario],
    queryFn: () => dashboardApi.getDashboard(scenario),
    // Don't refetch when real data is available
    enabled: analysisResult === null,
  });

  // If real analysis data exists, return it as a "successful" query-like shape
  if (analysisResult !== null) {
    return {
      data: analysisResult,
      isLoading: false,
      isError: false,
      error: null,
    };
  }

  return mockQuery;
}
