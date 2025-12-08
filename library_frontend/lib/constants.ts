/**
 * Константы приложения Mom's Club Library
 * Централизованное хранение всех констант для переиспользования
 */

// ==================== АДМИНЫ ====================

/** ID администраторов Telegram */
export const ADMIN_IDS = [534740911, 44054166] as const

/** Информация о группах админов */
export const ADMIN_GROUP_INFO: Record<string, { emoji: string; name: string }> = {
  creator: { emoji: '👑', name: "Основательница Mom's Club" },
  developer: { emoji: '💻', name: "Разработчик Mom's Club" },
  curator: { emoji: '🎯', name: "Куратор Mom's Club" },
}

// ==================== ЛОЯЛЬНОСТЬ ====================

/** Бейджи уровней лояльности */
export const LOYALTY_BADGES = {
  none: {
    label: 'Новичок',
    color: 'bg-gray-100 text-gray-600',
    icon: '🌱',
    bonus: '10% реферальный бонус',
    daysInClub: 0,
    nextLevel: 'Silver',
    daysToNext: 90,
  },
  silver: {
    label: 'Silver',
    color: 'bg-gradient-to-r from-gray-200 to-gray-300 text-gray-700',
    icon: '🥈',
    bonus: '15% реферальный бонус',
    daysInClub: 90,
    nextLevel: 'Gold',
    daysToNext: 180,
  },
  gold: {
    label: 'Gold',
    color: 'bg-gradient-to-r from-amber-100 to-amber-200 text-amber-700',
    icon: '🥇',
    bonus: '20% реферальный бонус',
    daysInClub: 180,
    nextLevel: 'Platinum',
    daysToNext: 365,
  },
  platinum: {
    label: 'Platinum',
    color: 'bg-gradient-to-r from-purple-100 to-purple-200 text-purple-700',
    icon: '💎',
    bonus: '30% реферальный бонус',
    daysInClub: 365,
    nextLevel: null,
    daysToNext: null,
  },
} as const

export type LoyaltyLevel = keyof typeof LOYALTY_BADGES

// ==================== ПОЛЬЗОВАТЕЛЬ ПО УМОЛЧАНИЮ ====================

/** Дефолтные данные пользователя */
export const DEFAULT_USER = {
  name: 'Гость',
  avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Guest&backgroundColor=ffdfbf',
  subscriptionDaysLeft: 0,
  subscriptionTotal: 30,
  loyaltyLevel: 'none' as LoyaltyLevel,
  daysInClub: 0,
  materialsViewed: 0,
  uniqueViewed: 0,
  favorites: 0,
  totalMaterials: 0,
  notifications: 0,
}

// ==================== ПАГИНАЦИЯ ====================

/** Количество материалов на странице */
export const ITEMS_PER_PAGE = {
  mobile: 4,
  desktop: 8,
} as const

// ==================== ССЫЛКИ ====================

/** Внешние ссылки */
export const EXTERNAL_URLS = {
  subscriptionBot: 'https://t.me/momsclubsubscribe_bot?start=renew',
  library: 'https://librarymomsclub.ru/library',
} as const

// ==================== API ====================

/** URL API */
export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://api.librarymomsclub.ru/api'
