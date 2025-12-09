/**
 * TypeScript типы для Mom's Club Library
 * Централизованные типы для переиспользования между компонентами
 */

import { LoyaltyLevel } from './constants'

// ==================== МАТЕРИАЛЫ ====================

/** Категория материала */
export interface Category {
  id: number
  name: string
  slug: string
  icon: string
  description?: string
  materials_count?: number
}

/** Материал библиотеки */
export interface Material {
  id: number
  title: string
  description?: string
  external_url?: string
  content?: string // HTML контент для редактора
  category_id?: number // Deprecated
  category?: Category // Deprecated, первая категория
  category_ids: number[] // Массив ID категорий
  categories?: Category[] // Массив категорий
  format: string
  cover_image?: string
  cover_url?: string // Оптимизированный URL обложки
  is_published: boolean
  is_featured: boolean
  views: number
  created_at: string
  favorites_count?: number
}

// ==================== УВЕДОМЛЕНИЯ ====================

/** Уведомление пользователя */
export interface Notification {
  id: number
  type: string
  title: string
  text: string
  link?: string
  is_read: boolean
  created_at: string
}

// ==================== ПОЛЬЗОВАТЕЛЬ ====================

/** Данные пользователя для отображения */
export interface UserDisplay {
  name: string
  avatar: string
  subscriptionDaysLeft: number
  subscriptionTotal: number
  loyaltyLevel: LoyaltyLevel
  daysInClub: number
  materialsViewed: number
  uniqueViewed: number
  favorites: number
  totalMaterials: number
  notifications: number
}

/** Данные пользователя из API */
export interface UserAPI {
  id: number
  telegram_id: number
  first_name: string
  username?: string
  photo_url?: string
  loyalty_level?: LoyaltyLevel
}

// ==================== РЕКОМЕНДАЦИИ ====================

/** Блок рекомендаций */
export interface Recommendations {
  type: string
  title: string
  materials: Material[]
}

// ==================== СТАТИСТИКА ====================

/** Статистика для админки */
export interface Stats {
  materials: {
    total: number
    published: number
    drafts: number
  }
  views_total: number
  favorites_total: number
  categories_total: number
}

// ==================== АКТИВНОСТЬ ====================

/** Активность пользователя */
export interface Activity {
  type: 'view' | 'favorite' | 'favorite_add' | 'favorite_remove'
  created_at: string
  user: {
    telegram_id: number
    first_name: string
    username?: string
    photo_url?: string
  }
  material: {
    id: number
    title: string
    icon: string
  }
}

/** Действие админа */
export interface AdminAction {
  id: number
  admin_id: number
  admin_name: string
  action: 'create' | 'edit' | 'delete' | 'publish' | 'unpublish'
  entity_type: 'material' | 'category' | 'tag'
  entity_id?: number
  entity_title?: string
  details?: string
  created_at: string
}

/** Админ пользователь */
export interface AdminUser {
  telegram_id: number
  first_name: string
  username?: string
  admin_group?: string
  photo_url?: string
}

// ==================== ХЕЛПЕРЫ ====================

/** Информация о типе ссылки */
export interface LinkTypeInfo {
  type: string
  icon: string
  label: string
  color: string
}
