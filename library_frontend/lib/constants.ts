/**
 * Константы приложения Mom's Club Library
 * Централизованное хранение всех констант для переиспользования
 */

// ==================== АДМИНЫ ====================

/** ID администраторов Telegram */
export const ADMIN_IDS: number[] = [534740911, 44054166, 5027032264]

/** Информация о группах админов */
export const ADMIN_GROUP_INFO: Record<string, { emoji: string; name: string; icon: string }> = {
  creator: { emoji: '', name: "Основательница Mom's Club", icon: 'crown' },
  developer: { emoji: '', name: "Разработчик Mom's Club", icon: 'code' },
  curator: { emoji: '', name: "Куратор Mom's Club", icon: 'target' },
}

// ==================== ЛОЯЛЬНОСТЬ ====================

/** Бейджи уровней лояльности */
export const LOYALTY_BADGES = {
  none: {
    label: 'Новичок',
    color: 'bg-[#F5E6D3]/70 text-[#8B8279]',
    icon: '🌱',
    bonus: '10% реферальный бонус',
    daysInClub: 0,
    nextLevel: 'Silver',
    daysToNext: 90,
  },
  silver: {
    label: 'Silver',
    color: 'bg-[#E8D4BA]/60 text-[#7A6B5A]',
    icon: '🥈',
    bonus: '15% реферальный бонус',
    daysInClub: 90,
    nextLevel: 'Gold',
    daysToNext: 180,
  },
  gold: {
    label: 'Gold',
    color: 'bg-[#D4C4A8]/70 text-[#6B5D4A]',
    icon: '🥇',
    bonus: '20% реферальный бонус',
    daysInClub: 180,
    nextLevel: 'Platinum',
    daysToNext: 365,
  },
  platinum: {
    label: 'Platinum',
    color: 'bg-[#C9A882]/50 text-[#5D4E3A]',
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
