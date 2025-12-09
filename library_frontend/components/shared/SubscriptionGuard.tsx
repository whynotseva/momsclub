'use client'

import { useEffect } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { useAuthContext } from '@/contexts/AuthContext'

// Страницы, требующие активную подписку
const SUBSCRIPTION_REQUIRED_PAGES = [
  '/',
  '/library',
  '/favorites',
  '/history',
]

/**
 * Компонент защиты роутов по подписке
 * Редиректит на /profile если нет подписки
 */
export function SubscriptionGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const { isAuthenticated, hasSubscription, loading } = useAuthContext()

  useEffect(() => {
    // Ждём загрузки
    if (loading) return
    
    // Если не авторизован — AuthContext сам редиректит на /login
    if (!isAuthenticated) return

    // Если нет подписки и пытается зайти на защищённую страницу
    const needsSubscription = SUBSCRIPTION_REQUIRED_PAGES.some(
      page => pathname === page || pathname.startsWith(page + '/')
    )

    if (needsSubscription && !hasSubscription) {
      router.replace('/profile')
    }
  }, [pathname, isAuthenticated, hasSubscription, loading, router])

  return <>{children}</>
}
