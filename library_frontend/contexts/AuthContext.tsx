'use client'

import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { api } from '@/lib/api'
import { ADMIN_IDS } from '@/lib/constants'

// Типы
interface User {
  name: string
  avatar: string
  username?: string
  telegramId?: number
  subscriptionDaysLeft: number
  hasSubscription: boolean
}

interface AuthContextType {
  user: User | null
  loading: boolean
  isAuthenticated: boolean
  isAdmin: boolean
  hasSubscription: boolean
  logout: () => void
  refreshUser: () => Promise<void>
}

// Контекст
const AuthContext = createContext<AuthContextType | null>(null)

// Публичные страницы (не требуют авторизации)
const PUBLIC_PAGES = ['/login', '/terms', '/privacy']

/**
 * Провайдер авторизации
 * Оборачивает приложение и предоставляет данные авторизации
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [isAdmin, setIsAdmin] = useState(false)

  const logout = useCallback(() => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('user')
    sessionStorage.removeItem('auth_error')
    setUser(null)
    setIsAdmin(false)
    router.push('/login')
  }, [router])

  const loadUser = useCallback(async () => {
    // Пропускаем проверку для публичных страниц
    if (PUBLIC_PAGES.includes(pathname)) {
      setLoading(false)
      return
    }

    const token = localStorage.getItem('access_token')
    
    if (!token) {
      setLoading(false)
      router.push('/login')
      return
    }

    try {
      // Загружаем данные пользователя и проверяем подписку
      const [meResponse, subResponse] = await Promise.all([
        api.get('/auth/me'),
        api.get('/auth/check-subscription')
      ])
      
      const userData = meResponse.data
      const subData = subResponse.data
      
      // Сохраняем статус подписки (но НЕ блокируем вход)
      const hasActiveSub = subData.has_active_subscription

      const userIsAdmin = ADMIN_IDS.includes(userData.telegram_id)
      
      setUser({
        name: userData.first_name || 'Гость',
        avatar: userData.photo_url || `https://api.dicebear.com/7.x/avataaars/svg?seed=${userData.username || userData.first_name}&backgroundColor=ffdfbf`,
        username: userData.username,
        telegramId: userData.telegram_id,
        subscriptionDaysLeft: subData.days_left || 0,
        hasSubscription: hasActiveSub,
      })
      setIsAdmin(userIsAdmin)
      
      // Сохраняем в localStorage для fallback
      localStorage.setItem('user', JSON.stringify(userData))
      
    } catch (error) {
      console.error('Auth error:', error)
      // Пробуем fallback на localStorage
      const savedUser = localStorage.getItem('user')
      if (savedUser) {
        try {
          const userData = JSON.parse(savedUser)
          setUser({
            name: userData.first_name || 'Гость',
            avatar: userData.photo_url || '',
            username: userData.username,
            telegramId: userData.telegram_id,
            subscriptionDaysLeft: 0,
            hasSubscription: false, // fallback — предполагаем нет
          })
          setIsAdmin(ADMIN_IDS.includes(userData.telegram_id))
        } catch {
          logout()
        }
      } else {
        logout()
      }
    } finally {
      setLoading(false)
    }
  }, [pathname, router, logout])

  // Загружаем пользователя при монтировании и смене страницы
  useEffect(() => {
    loadUser()
  }, [loadUser])

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        isAuthenticated: !!user,
        isAdmin,
        hasSubscription: user?.hasSubscription ?? false,
        logout,
        refreshUser: loadUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

/**
 * Хук для доступа к контексту авторизации
 */
export function useAuthContext(): AuthContextType {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuthContext must be used within AuthProvider')
  }
  return context
}
