/**
 * API клиент для связи с backend
 * С retry логикой и кэшированием
 */

import axios, { AxiosError } from 'axios';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001/api';

// ============================================
// ПРОСТОЙ КЭШ В ПАМЯТИ
// ============================================
interface CacheEntry {
  data: unknown;
  timestamp: number;
}
const cache = new Map<string, CacheEntry>();
const CACHE_TTL = 5 * 60 * 1000; // 5 минут

function getCached<T>(key: string): T | null {
  const cached = cache.get(key);
  if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
    return cached.data as T;
  }
  cache.delete(key);
  return null;
}

function setCache(key: string, data: unknown) {
  cache.set(key, { data, timestamp: Date.now() });
}

export function clearCache() {
  cache.clear();
}

// Создаём axios instance
export const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000, // 30 секунд таймаут
});

// Добавляем токен к каждому запросу
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Обработка ошибок с retry
api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as { _retry?: boolean } & typeof error.config;
    
    // Не ретраим если уже ретраили или 401/403
    if (config?._retry || error.response?.status === 401 || error.response?.status === 403) {
      // При 401 (не авторизован) или 403 (нет доступа) — очищаем данные и редиректим на логин
      if (error.response?.status === 401 || error.response?.status === 403) {
        console.log('🔐 Сессия истекла, перенаправляем на вход...');
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
        // Очищаем кэш API
        cache.clear();
        // Редирект на логин (если ещё не там)
        if (typeof window !== 'undefined' && !window.location.pathname.includes('/login')) {
          window.location.href = '/login';
        }
      }
      return Promise.reject(error);
    }
    
    // Ретраим при сетевых ошибках или 5xx
    if (!error.response || error.response.status >= 500) {
      if (config) config._retry = true;
      await new Promise(r => setTimeout(r, 1000));
      return api(config!);
    }
    
    return Promise.reject(error);
  }
);

// ============================================
// ТИПЫ
// ============================================

export interface User {
  telegram_id: number;
  first_name?: string;
  username?: string;
  has_active_subscription: boolean;
  subscription_end?: string;
}

export interface Material {
  id: number;
  title: string;
  description?: string;
  content?: string;
  category_id: number;
  category?: Category;
  format: string;
  level?: string;
  duration?: number;
  viral_score?: number;
  cover_image?: string;
  is_featured: boolean;
  views: number;
  created_at: string;
  tags: Tag[];
  attachments?: Attachment[];
}

export interface Category {
  id: number;
  name: string;
  slug: string;
  description?: string;
  icon?: string;
  position: number;
  materials_count: number;
}

export interface Tag {
  id: number;
  name: string;
  slug: string;
  category?: string;
}

export interface Attachment {
  id: number;
  type: string;
  url: string;
  title?: string;
  file_size?: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// ============================================
// API МЕТОДЫ
// ============================================

export const authAPI = {
  // Авторизация через Telegram
  telegramLogin: (authData: { id: number; first_name?: string; last_name?: string; username?: string; photo_url?: string; auth_date: number; hash: string }) => 
    api.post<{ access_token: string; user: User }>('/auth/telegram', authData),
  
  // Текущий пользователь
  me: () => 
    api.get<User>('/auth/me'),
  
  // Проверка подписки
  checkSubscription: () => 
    api.get<{ has_active_subscription: boolean; subscription_end?: string; days_left?: number }>('/auth/check-subscription'),
};

export const materialsAPI = {
  // Список материалов
  getList: (params?: {
    search?: string;
    category_id?: number;
    format?: string;
    level?: string;
    is_featured?: boolean;
    page?: number;
    page_size?: number;
    sort?: string;
  }) => 
    api.get<PaginatedResponse<Material>>('/materials', { params }),
  
  // Детали материала
  getById: (id: number) => 
    api.get<Material>(`/materials/${id}`),
  
  // Записать просмотр
  recordView: (id: number, duration_seconds?: number) => 
    api.post(`/materials/${id}/view`, { duration_seconds }),
  
  // Избранные ("Выбор Полины")
  getFeatured: (limit = 10) => 
    api.get<Material[]>('/materials/featured/list', { params: { limit } }),
  
  // Популярные
  getPopular: (limit = 10) => 
    api.get<Material[]>('/materials/popular/list', { params: { limit } }),
};

export const categoriesAPI = {
  // Список категорий (с кэшированием)
  getList: async () => {
    const cacheKey = 'categories_list';
    const cached = getCached(cacheKey);
    if (cached) return { data: cached };
    
    const response = await api.get<Category[]>('/categories');
    setCache(cacheKey, response.data);
    return response;
  },
  
  // Детали категории
  getById: (id: number) => 
    api.get<Category>(`/categories/${id}`),
};

export const tagsAPI = {
  // Список тегов
  getList: (category?: string) => 
    api.get<Tag[]>('/tags', { params: { category } }),
};

export const favoritesAPI = {
  // Список избранного
  getList: () => 
    api.get<Material[]>('/favorites'),
  
  // Добавить в избранное
  add: (materialId: number) => 
    api.post(`/favorites/${materialId}`),
  
  // Удалить из избранного
  remove: (materialId: number) => 
    api.delete(`/favorites/${materialId}`),
  
  // Проверить статус
  check: (materialId: number) => 
    api.get<{ is_favorite: boolean }>(`/favorites/check/${materialId}`),
};

export const historyAPI = {
  // История просмотров
  getList: (limit = 50) => 
    api.get<Material[]>('/history', { params: { limit } }),
};
