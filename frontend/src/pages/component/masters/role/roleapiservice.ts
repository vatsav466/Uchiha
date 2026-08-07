// roleapiservice.ts
import { apiClient } from '@/services/apiClient';

// All paths are relative — nginx on :5378 proxies /api/* → FastAPI on :8002.
const BASE = '/api';

export interface RoleMasterResponse {
  data: {
    role: string;
    sap_id: string;
    email: string;
    district: string;
    state: string;
    zone: string;
    id: number;
    updated_at: string;
    location_name: string;
    bu: string;
    user_name: string;
    phone_no: string;
    city: string;
    region: string;
    escalation_level: string;
    created_at: string;
    entity_id: string | null;
  }[];
  total: number;
}

export interface RoleData {
  id: string;
  sapCode: string;
  name: string;
  email: string;
  phone: string;
  position: string;
  region: string;
  state: string;
  city: string;
  territory: string;
  siteName: string;
  escalationLevel: string;
}

export interface PaginatedResponse<T> {
  data: T[];
  total: number;
}

export const RoleMasterService = {
  async getAllRoles(params?: {
    q?: string;
    skip?: number;
    limit?: number;
    sort?: string;
    fields?: string;
    view?: string;
  }): Promise<PaginatedResponse<RoleData>> {
    try {
      const response = await apiClient.get<RoleMasterResponse>(
        `${BASE}/rolemaster`,
        {
          params: {
            ...params,
            limit: params?.limit || 10,
            skip: params?.skip || 0,
          },
        }
      );

      const mappedData = response.data.data.map((item) => ({
        id: item.id.toString(),
        sapCode: item.sap_id,
        name: item.user_name,
        email: item.email,
        phone: item.phone_no,
        position: item.role,
        region: item.region,
        state: item.state,
        city: item.city,
        territory: item.district,
        siteName: item.location_name,
        escalationLevel: item.escalation_level,
      }));

      return {
        data: mappedData,
        total: response.data.total,
      };
    } catch (error) {
      console.error('Error fetching roles:', error);
      throw error;
    }
  },

  async createRole(roleData: Partial<RoleData>) {
    try {
      const response = await apiClient.post(`${BASE}/rolemaster`, roleData);
      return response.data;
    } catch (error) {
      console.error('Error creating role:', error);
      throw error;
    }
  },

  async updateRole(id: string, roleData: Partial<RoleData>) {
    try {
      const response = await apiClient.put(`${BASE}/rolemaster/${id}`, roleData);
      return response.data;
    } catch (error) {
      console.error('Error updating role:', error);
      throw error;
    }
  },

  async deleteRole(id: string) {
    try {
      const response = await apiClient.delete(`${BASE}/rolemaster/${id}`);
      return response.data;
    } catch (error) {
      console.error('Error deleting role:', error);
      throw error;
    }
  },

  async uploadCsv(formData: FormData) {
    try {
      const response = await apiClient.post(
        `${BASE}/rolemaster/upload_role_master`,
        formData,
        {
          headers: {
            'Content-Type': 'multipart/form-data',
            accept: 'application/json',
          },
        }
      );

      if (Array.isArray(response.data) && response.data.length === 2) {
        return {
          success: response.data[0],
          message: response.data[1],
        };
      }

      throw new Error('Unexpected response format');
    } catch (error) {
      console.error('Error uploading CSV:', error);
      throw error;
    }
  },

  async downloadTemplate() {
    try {
      const response = await apiClient.post(
        `${BASE}/rolemaster/download_template`,
        {},
        {
          responseType: 'blob',
          headers: {
            accept: 'application/json',
            'Content-Type': 'application/json',
          },
        }
      );
      return response.data;
    } catch (error) {
      console.error('Error downloading template:', error);
      throw error;
    }
  },

  async downloadCsv() {
    try {
      const response = await apiClient.post<{
        status: boolean;
        message: string;
        data: string;
      }>(`${BASE}/rolemaster/download_role_master`, {});

      if (!response.data.status || !response.data.data) {
        throw new Error('Failed to get download path');
      }

      // Backend returns a relative path (e.g. /downloads/file.csv)
      const fileResponse = await apiClient.get(response.data.data, {
        responseType: 'arraybuffer',
        headers: {
          'Content-Type': 'application/octet-stream',
        },
      });

      return {
        data: fileResponse.data,
        success: true,
        message: 'File fetched successfully',
      };
    } catch (error) {
      console.error('Error downloading CSV:', error);
      throw error;
    }
  },
};
