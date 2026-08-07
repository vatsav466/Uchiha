// queryService.ts
import { apiClient } from "@/services/apiClient";

// All paths are relative — nginx on :5378 proxies /api/* → FastAPI on :8002.

export interface DatabaseResponse {
  status: boolean;
  message: string;
  data: string[];
}

export const databaseService = {
  getDatabases: async (): Promise<string[]> => {
    try {
      const response = await apiClient.get(`/api/charts/get_databases?connection_id=4`);

      if (!response.status) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data: DatabaseResponse = response.data;

      if (!data.status) {
        throw new Error(data.message || 'Failed to fetch databases');
      }

      return data.data;
    } catch (error) {
      console.error('Error fetching databases:', error);
      throw error;
    }
  },
};

export default databaseService;
