'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { api } from '@/lib/api'
import { usePresence } from '@/hooks/usePresence'
import { usePushNotifications } from '@/hooks/usePushNotifications'
import { QuoteOfDay, MobileNav, PushPromoModal, CategoryFilter } from '@/components/library'

// Список админов
const ADMIN_IDS = [534740911, 44054166]

// Дефолтные данные пользователя (будут заменены реальными)
const defaultUser = {
  name: 'Гость',
  avatar: 'https://api.dicebear.com/7.x/avataaars/svg?seed=Guest&backgroundColor=ffdfbf',
  subscriptionDaysLeft: 0,
  subscriptionTotal: 30,
  loyaltyLevel: 'none' as const,
  daysInClub: 0,
  materialsViewed: 0,
  uniqueViewed: 0,
  favorites: 0,
  totalMaterials: 0,
  notifications: 0,
}

const loyaltyBadges = {
  none: { label: 'Новичок', color: 'bg-gray-100 text-gray-600', icon: '🌱', bonus: '10% реферальный бонус', daysInClub: 0, nextLevel: 'Silver', daysToNext: 90 },
  silver: { label: 'Silver', color: 'bg-gradient-to-r from-gray-200 to-gray-300 text-gray-700', icon: '🥈', bonus: '15% реферальный бонус', daysInClub: 90, nextLevel: 'Gold', daysToNext: 180 },
  gold: { label: 'Gold', color: 'bg-gradient-to-r from-amber-100 to-amber-200 text-amber-700', icon: '🥇', bonus: '20% реферальный бонус', daysInClub: 180, nextLevel: 'Platinum', daysToNext: 365 },
  platinum: { label: 'Platinum', color: 'bg-gradient-to-r from-purple-100 to-purple-200 text-purple-700', icon: '💎', bonus: '30% реферальный бонус', daysInClub: 365, nextLevel: null, daysToNext: null },
}

// Категории загружаются из API (apiCategories)

// 365 мотивационных цитат на год

// Тип уведомления
interface Notification {
  id: number
  type: string
  title: string
  text: string
  link?: string
  is_read: boolean
  created_at: string
}


// Тип материала
interface Material {
  id: number
  title: string
  description?: string
  external_url?: string
  category_id?: number  // Deprecated
  category?: { name: string; slug: string; icon: string }  // Deprecated, первая категория
  category_ids?: number[]  // Новое: массив ID категорий
  categories?: { id: number; name: string; slug: string; icon: string }[]  // Новое: массив категорий
  format?: string
  cover_image?: string
  is_published: boolean
  is_featured: boolean
  views: number
  created_at: string
  favorites_count?: number  // Количество лайков
}

// Тип категории
interface Category {
  id: number
  name: string
  slug: string
  icon: string
  description?: string
  materials_count?: number
}

export default function LibraryPage() {
  const router = useRouter()
  const [loading, setLoading] = useState(true)
  const [user, setUser] = useState(defaultUser)
  const [isAdmin, setIsAdmin] = useState(false)
  
  // WebSocket для отслеживания онлайн пользователей
  usePresence('library')
  
  // Push уведомления
  const { isSupported: pushSupported, isSubscribed: pushSubscribed, toggle: togglePush, isLoading: pushLoading } = usePushNotifications()
  
  const [activeCategory, setActiveCategoryState] = useState('all')
  
  // Обёртка для сброса пагинации при смене категории
  const setActiveCategory = (category: string) => {
    setActiveCategoryState(category)
    setVisibleCount(8) // Сбрасываем к начальному значению
  }
  const [showNotifications, setShowNotifications] = useState(false)
  const [showProfileMenu, setShowProfileMenu] = useState(false)
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [showPushPromo, setShowPushPromo] = useState(false)
  
  // Скролл для скрытия/показа меню
  const [showHeader, setShowHeader] = useState(true)
  const [showMobileNav, setShowMobileNav] = useState(true)
  const [lastScrollY, setLastScrollY] = useState(0)
  
  // Реальные данные из API
  const [materials, setMaterials] = useState<Material[]>([])
  const [apiCategories, setApiCategories] = useState<Category[]>([])
  const [favoriteIds, setFavoriteIds] = useState<Set<number>>(new Set())
  const [searchQuery, setSearchQuery] = useState('')
  
  // Рекомендации "Вам понравится"
  const [recommendations, setRecommendations] = useState<{type: string, title: string, materials: Material[]}>({type: '', title: '', materials: []})
  
  // Пагинация материалов (4 на мобилке, 8 на десктопе)
  const [visibleCount, setVisibleCount] = useState(4) // Начинаем с 4 (мобилка)
  const [isMobile, setIsMobile] = useState(true)
  const [isPWA, setIsPWA] = useState(false)
  
  // Определяем мобильность и PWA на клиенте
  useEffect(() => {
    const checkMobile = () => {
      const mobile = window.innerWidth < 768
      setIsMobile(mobile)
      // Устанавливаем начальное количество при первой загрузке
      if (visibleCount === 4 && !mobile) {
        setVisibleCount(8)
      }
    }
    // Проверяем PWA режим
    const isStandalone = window.matchMedia('(display-mode: standalone)').matches ||
                         (window.navigator as unknown as { standalone?: boolean }).standalone === true
    setIsPWA(isStandalone)
    
    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
  }, [])
  
  const ITEMS_PER_PAGE = isMobile ? 4 : 8

  // Прочитать все уведомления
  const markAllAsRead = async () => {
    try {
      await api.post('/materials/notifications/read-all')
      setNotifications(notifications.map(n => ({ ...n, is_read: true })))
      setUser(prev => ({ ...prev, notifications: 0 }))
    } catch (error) {
      console.error('Error marking all as read:', error)
    }
  }

  // Прочитать одно уведомление
  const markAsRead = async (id: number) => {
    try {
      await api.post(`/materials/notifications/${id}/read`)
      setNotifications(notifications.map(n => 
        n.id === id ? { ...n, is_read: true } : n
      ))
      const unreadCount = notifications.filter(n => !n.is_read && n.id !== id).length
      setUser(prev => ({ ...prev, notifications: unreadCount }))
    } catch (error) {
      console.error('Error marking as read:', error)
    }
  }

  // Открыть материал и записать просмотр
  const openMaterial = (material: Material) => {
    // Открываем ссылку в новой вкладке через создание <a> элемента
    if (material.external_url) {
      const link = document.createElement('a')
      link.href = material.external_url
      link.target = '_blank'
      link.rel = 'noopener noreferrer'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    }
    
    // Записываем просмотр асинхронно
    api.post(`/materials/${material.id}/view`)
      .then(() => {
        setUser(prev => ({ ...prev, materialsViewed: prev.materialsViewed + 1 }))
      })
      .catch(error => {
        console.error('Error recording view:', error)
      })
  }

  // Добавить/убрать из избранного
  const toggleFavorite = async (materialId: number) => {
    const isFavorite = favoriteIds.has(materialId)
    
    try {
      if (isFavorite) {
        await api.delete(`/materials/${materialId}/favorite`)
        setFavoriteIds(prev => {
          const newSet = new Set(prev)
          newSet.delete(materialId)
          setUser(u => ({ ...u, favorites: newSet.size }))
          return newSet
        })
        // Уменьшаем счётчик лайков на карточке
        setMaterials(prev => prev.map(m => 
          m.id === materialId ? { ...m, favorites_count: Math.max(0, (m.favorites_count ?? 1) - 1) } : m
        ))
      } else {
        await api.post(`/materials/${materialId}/favorite`)
        setFavoriteIds(prev => {
          const newSet = new Set(prev).add(materialId)
          setUser(u => ({ ...u, favorites: newSet.size }))
          return newSet
        })
        // Увеличиваем счётчик лайков на карточке
        setMaterials(prev => prev.map(m => 
          m.id === materialId ? { ...m, favorites_count: (m.favorites_count ?? 0) + 1 } : m
        ))
      }
    } catch (error) {
      console.error('Error toggling favorite:', error)
    }
  }

  useEffect(() => {
    const loadUserData = async () => {
      // Проверяем токен
      const token = localStorage.getItem('access_token')
      if (!token) {
        router.push('/login')
        return
      }

      // Загружаем данные пользователя из API
      try {
        const meResponse = await api.get('/auth/me')
        const userData = meResponse.data
        setUser(prev => ({
          ...prev,
          name: userData.first_name || 'Гость',
          avatar: userData.photo_url || `https://api.dicebear.com/7.x/avataaars/svg?seed=${userData.username || userData.first_name}&backgroundColor=ffdfbf`,
          loyaltyLevel: userData.loyalty_level || 'none',
        }))
        // Проверяем админа
        if (ADMIN_IDS.includes(userData.telegram_id)) {
          setIsAdmin(true)
        }
        // Обновляем localStorage
        localStorage.setItem('user', JSON.stringify(userData))
      } catch {
        // Fallback на localStorage
        const savedUser = localStorage.getItem('user')
        if (savedUser) {
          try {
            const userData = JSON.parse(savedUser)
            setUser(prev => ({
              ...prev,
              name: userData.first_name || 'Гость',
              avatar: userData.photo_url || `https://api.dicebear.com/7.x/avataaars/svg?seed=${userData.username || userData.first_name}&backgroundColor=ffdfbf`,
              loyaltyLevel: userData.loyalty_level || 'none',
            }))
          } catch (err) {
            console.error('Error parsing user data:', err)
          }
        }
      }

      // Загружаем данные подписки из API
      try {
        const response = await api.get('/auth/check-subscription')
        const subData = response.data
        
        // Проверяем что подписка активна
        if (!subData.has_active_subscription) {
          // Подписка истекла — кикаем на страницу входа
          localStorage.removeItem('access_token')
          localStorage.removeItem('user')
          alert('Ваша подписка истекла. Продлите подписку через @momsclubsubscribe_bot')
          router.push('/login')
          return
        }
        
        setUser(prev => ({
          ...prev,
          subscriptionDaysLeft: subData.days_left || 0,
        }))
      } catch (error) {
        console.error('Error loading subscription:', error)
        // При ошибке авторизации — кикаем
        localStorage.removeItem('access_token')
        localStorage.removeItem('user')
        router.push('/login')
        return
      }

      // Загружаем категории
      try {
        const catResponse = await api.get('/categories')
        setApiCategories(catResponse.data)
      } catch (error) {
        console.error('Error loading categories:', error)
      }

      // Загружаем материалы
      try {
        const matResponse = await api.get('/materials')
        const items = matResponse.data.items || []
        setMaterials(items)
        setUser(prev => ({
          ...prev,
          totalMaterials: matResponse.data.total || items.length,
        }))
      } catch (error) {
        console.error('Error loading materials:', error)
      }

      // Загружаем избранные ID для отметки сердечек И счётчик
      try {
        const favResponse = await api.get('/materials/favorites/my')
        const favIds = new Set<number>((favResponse.data || []).map((m: Material) => m.id))
        setFavoriteIds(favIds)
        setUser(prev => ({ ...prev, favorites: favIds.size }))
      } catch (error) {
        console.error('Error loading favorites:', error)
      }

      // Загружаем статистику просмотров
      try {
        const statsResponse = await api.get('/materials/stats/my')
        setUser(prev => ({ 
          ...prev, 
          materialsViewed: statsResponse.data.materials_viewed || 0,
          uniqueViewed: statsResponse.data.unique_viewed || 0,
        }))
      } catch (error) {
        console.error('Error loading stats:', error)
      }

      // Загружаем уведомления
      try {
        const notifResponse = await api.get('/materials/notifications/my')
        setNotifications(notifResponse.data.notifications || [])
        setUser(prev => ({ ...prev, notifications: notifResponse.data.unread_count || 0 }))
      } catch (error) {
        console.error('Error loading notifications:', error)
      }

      // Загружаем рекомендации
      try {
        const recResponse = await api.get('/materials/feed/recommendations')
        setRecommendations(recResponse.data)
      } catch (error) {
        console.error('Error loading recommendations:', error)
      }

      setLoading(false)
    }

    loadUserData()
  }, [router])

  // Показ промо для Push уведомлений
  useEffect(() => {
    if (!loading && pushSupported && !pushSubscribed && !pushLoading) {
      // Проверяем не показывали ли уже промо
      const pushPromoDismissed = localStorage.getItem('push_promo_dismissed')
      if (!pushPromoDismissed) {
        // Показываем промо через 3 секунды после загрузки
        const timer = setTimeout(() => {
          setShowPushPromo(true)
        }, 3000)
        return () => clearTimeout(timer)
      }
    }
  }, [loading, pushSupported, pushSubscribed, pushLoading])

  // Отслеживание скролла для скрытия/показа меню
  useEffect(() => {
    const handleScroll = () => {
      const currentScrollY = window.scrollY
      const scrollDiff = currentScrollY - lastScrollY
      
      // Показываем меню если скроллим вверх или в самом верху
      if (currentScrollY < 50) {
        setShowHeader(true)
        setShowMobileNav(true)
      } else if (scrollDiff > 10) {
        // Скроллим вниз — скрываем
        setShowHeader(false)
        setShowMobileNav(false)
      } else if (scrollDiff < -10) {
        // Скроллим вверх — показываем
        setShowHeader(true)
        setShowMobileNav(true)
      }
      
      setLastScrollY(currentScrollY)
    }

    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [lastScrollY])

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-[#FDFCFA] via-[#FBF8F3] to-[#F5EFE6] flex flex-col items-center justify-center">
        <img 
          src="/logolibrary.svg" 
          alt="LibriMomsClub" 
          className="h-20 sm:h-24 w-auto mb-4 animate-pulse"
        />
        <p className="text-[#8B8279] text-sm">Загрузка...</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#FDFCFA] via-[#FBF8F3] to-[#F5EFE6] relative">
      {/* Premium gradient orbs */}
      <div className="fixed -top-40 -right-40 w-[600px] h-[600px] bg-gradient-to-br from-[#E8D5C4]/30 via-[#D4C4B0]/15 to-transparent rounded-full blur-3xl pointer-events-none"></div>
      <div className="fixed -bottom-40 -left-40 w-[500px] h-[500px] bg-gradient-to-tr from-[#C9B89A]/15 to-transparent rounded-full blur-3xl pointer-events-none"></div>

      {/* Header с плавной анимацией */}
      <header 
        className={`fixed top-0 left-0 right-0 z-50 border-b border-white/50 shadow-lg transition-transform duration-300 ease-in-out ${showHeader ? 'translate-y-0' : '-translate-y-full'}`} 
        style={{ background: 'rgba(255,255,255,0.55)', backdropFilter: 'blur(20px) saturate(180%)', paddingTop: 'env(safe-area-inset-top)' }}
      >
        <div className="max-w-7xl mx-auto px-6 py-2">
          <div className="flex items-center justify-between">
            <a href="/library" className="flex items-center space-x-2 group relative">
              <span className="text-2xl absolute -top-1 -left-2 rotate-[-15deg] drop-shadow-md">🎅</span>
              <img 
                src="/logolibrary.svg" 
                alt="LibriMomsClub" 
                className="h-8 w-auto group-hover:scale-105 transition-transform ml-5"
              />
            </a>
            
            <nav className="hidden md:flex space-x-8">
              <a href="/library" className="text-[#B08968] font-semibold">Библиотека</a>
              <a href="/favorites" className="text-[#8B8279] hover:text-[#B08968] transition-colors">Избранное</a>
              <a href="/history" className="text-[#8B8279] hover:text-[#B08968] transition-colors">История</a>
            </nav>
            
            <div className="flex items-center space-x-4">
              {/* Уведомления */}
              <div className="relative">
                <button 
                  onClick={() => setShowNotifications(!showNotifications)}
                  className="relative p-2 hover:bg-[#F5E6D3]/50 rounded-xl transition-colors"
                >
                  <svg className="w-6 h-6 text-[#B08968]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                  </svg>
                  {user.notifications > 0 && (
                    <span className="absolute -top-1 -right-1 w-5 h-5 bg-red-500 text-white text-xs font-bold rounded-full flex items-center justify-center animate-pulse">
                      {user.notifications}
                    </span>
                  )}
                </button>
                
                {/* Overlay для закрытия dropdown */}
                {showNotifications && (
                  <div 
                    className="fixed inset-0 z-40 bg-black/5" 
                    onClick={() => setShowNotifications(false)}
                  />
                )}
                
                {/* Dropdown уведомлений */}
                {showNotifications && (
                  <div 
                    className="absolute right-0 top-12 w-80 bg-white rounded-2xl shadow-2xl border border-[#E8D4BA]/40 z-50 overflow-hidden"
                  >
                      {/* Header */}
                      <div className="px-4 py-3 border-b border-[#E8D4BA]/30 flex items-center justify-between">
                        <span className="font-bold text-[#2D2A26]">Уведомления</span>
                        <button 
                          onClick={markAllAsRead}
                          className="text-xs text-[#B08968] hover:text-[#8B7355] font-medium"
                        >
                          Прочитать все
                        </button>
                      </div>
                      
                      {/* Notifications list */}
                      <div className="max-h-80 overflow-y-auto">
                        {notifications.length === 0 ? (
                          <div className="px-4 py-8 text-center text-[#8B8279]">
                            <span className="text-3xl mb-2 block">✨</span>
                            Нет новых уведомлений
                          </div>
                        ) : (
                          notifications.map((notif) => (
                            <div 
                              key={notif.id}
                              onClick={() => markAsRead(notif.id)}
                              className={`px-4 py-3 border-b border-[#E8D4BA]/20 hover:bg-[#FBF8F3] cursor-pointer transition-colors ${
                                !notif.is_read ? 'bg-[#F5E6D3]/20' : ''
                              }`}
                            >
                              <div className="flex items-start space-x-3">
                                <div className={`w-2 h-2 rounded-full mt-2 flex-shrink-0 ${
                                  !notif.is_read ? 'bg-[#B08968]' : 'bg-gray-300'
                                }`}></div>
                                <div className="flex-1">
                                  <p className="font-semibold text-sm text-[#2D2A26]">{notif.title}</p>
                                  <p className="text-sm text-[#5C5650]">{notif.text}</p>
                                  <p className="text-xs text-[#8B8279] mt-1">
                                    {new Date(notif.created_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
                                  </p>
                                </div>
                              </div>
                            </div>
                          ))
                        )}
                      </div>
                      
                      {/* Footer с Push toggle */}
                      <div className="px-4 py-3 border-t border-[#E8D4BA]/30">
                        {pushSupported && (
                          <button 
                            onClick={togglePush}
                            disabled={pushLoading}
                            className={`w-full mb-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2 ${
                              pushSubscribed 
                                ? 'bg-green-100 text-green-700 hover:bg-green-200' 
                                : 'bg-[#F5E6D3] text-[#8B7355] hover:bg-[#E8D4BA]'
                            }`}
                          >
                            {pushLoading ? (
                              '⏳ Загрузка...'
                            ) : pushSubscribed ? (
                              <>✅ Push включены (нажми чтобы отключить)</>
                            ) : (
                              <><svg className="w-4 h-4 inline mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" /></svg> Включить Push</>
                            )}
                          </button>
                        )}
                        <button 
                          onClick={() => setShowNotifications(false)}
                          className="w-full text-sm text-[#B08968] hover:text-[#8B7355] font-medium"
                        >
                          Закрыть
                        </button>
                      </div>
                    </div>
                )}
              </div>
              
              {/* Аватар с выпадающим меню */}
              <div className="relative">
                <button
                  onClick={() => setShowProfileMenu(!showProfileMenu)}
                  className="flex items-center space-x-2"
                >
                  <img 
                    src={user.avatar || ''} 
                    alt={user.name}
                    className="w-9 h-9 rounded-full border-2 border-[#E8D4BA] object-cover cursor-pointer hover:border-[#B08968] transition-colors"
                  />
                  <span className="text-[#8B8279] text-sm font-medium hidden md:block">
                    Выйти
                  </span>
                </button>
                
                {/* Выпадающее меню профиля */}
                {showProfileMenu && (
                  <div className="absolute right-0 top-12 bg-white rounded-xl shadow-xl border border-[#E8D4BA]/50 py-2 min-w-[160px] z-50">
                    <div className="px-4 py-2 border-b border-gray-100">
                      <p className="text-sm font-medium text-[#2D2A26]">{user.name}</p>
                      <p className="text-xs text-[#8B8279]">@{localStorage.getItem('user') ? JSON.parse(localStorage.getItem('user') || '{}').username : ''}</p>
                    </div>
                    {isAdmin && (
                      <Link 
                        href="/admin"
                        className="w-full px-4 py-2 text-left text-sm text-[#B08968] hover:bg-[#F5E6D3] transition-colors flex items-center gap-2"
                      >
                        <span>⚙️</span> Админ-панель
                      </Link>
                    )}
                    <button 
                      onClick={() => {
                        localStorage.removeItem('access_token')
                        localStorage.removeItem('user')
                        sessionStorage.removeItem('auth_error')
                        router.push('/login')
                      }}
                      className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 transition-colors flex items-center gap-2"
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                      </svg>
                      Выйти
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content — с отступом под fixed header */}
      <main className="max-w-7xl mx-auto px-4 py-8" style={{ paddingTop: 'calc(5rem + env(safe-area-inset-top, 0px))' }}>
        {/* Приветствие + Профиль */}
        <div className="mb-10 grid lg:grid-cols-3 gap-6">
          {/* Приветствие */}
          <div className="lg:col-span-2 relative">
            <div className="absolute inset-0 bg-gradient-to-r from-[#C9A882]/10 to-[#B08968]/5 rounded-3xl blur-2xl"></div>
            <div className="relative bg-white/80 backdrop-blur-sm rounded-3xl p-6 lg:p-8 border border-[#E8D4BA]/40 shadow-xl shadow-[#C9A882]/10 h-full">
              <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
                <div className="flex-1">
                  <h2 className="text-xl lg:text-2xl font-bold text-[#2D2A26] mb-2">
                    👋 Привет, {user.name}!
                  </h2>
                  <p className="text-[#5C5650] text-sm lg:text-base mb-4">
                    Эксклюзивные идеи для Reels, гайды и стратегии роста
                  </p>
                  
                  {/* Статистика */}
                  <div className="flex items-center gap-4 text-sm">
                    <div className="flex items-center space-x-1">
                      <span>👁️</span>
                      <span><strong>{user.materialsViewed}</strong> просмотрено</span>
                    </div>
                    <div className="flex items-center space-x-1">
                      <span>⭐</span>
                      <span><strong>{user.favorites}</strong> в избранном</span>
                    </div>
                  </div>
                  
                  {/* Прогресс изучения — только мобильный */}
                  <div className="lg:hidden mt-4 bg-[#F5E6D3]/50 rounded-xl p-3">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-medium text-[#8B8279]">📚 Изучено</span>
                      <span className="text-xs font-bold text-[#B08968]">{user.uniqueViewed} из {user.totalMaterials || 0}</span>
                    </div>
                    <div className="h-2 bg-white rounded-full overflow-hidden">
                      <div 
                        className="h-full bg-gradient-to-r from-[#B08968] to-[#C9A882] rounded-full"
                        style={{ width: `${user.totalMaterials > 0 ? Math.min((user.uniqueViewed / user.totalMaterials) * 100, 100) : 0}%` }}
                      ></div>
                    </div>
                  </div>
                </div>
                
                {/* Статус лояльности */}
                <div className={`flex items-center space-x-2 px-3 py-1.5 rounded-full whitespace-nowrap text-sm ${loyaltyBadges[user.loyaltyLevel as keyof typeof loyaltyBadges].color}`}>
                  <span>Статус:</span>
                  <span>{loyaltyBadges[user.loyaltyLevel as keyof typeof loyaltyBadges].icon}</span>
                  <span className="font-bold">{loyaltyBadges[user.loyaltyLevel as keyof typeof loyaltyBadges].label}</span>
                </div>
              </div>
            </div>
          </div>
          
          {/* Карточка подписки */}
          <div className="relative">
            <div className="absolute inset-0 bg-gradient-to-br from-[#B08968]/10 to-[#C9A882]/5 rounded-3xl blur-xl"></div>
            <div className="relative bg-white/90 backdrop-blur-sm rounded-3xl p-6 border border-[#E8D4BA]/40 shadow-xl shadow-[#C9A882]/10 h-full">
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm font-medium text-[#8B8279]">Подписка</span>
                {user.subscriptionDaysLeft <= 7 && (
                  <span className="text-xs bg-red-100 text-red-600 px-2 py-1 rounded-full font-medium animate-pulse">
                    ⚠️ Скоро истекает
                  </span>
                )}
              </div>
              
              <div className="text-center mb-4">
                <div className="text-5xl font-black text-[#2D2A26]">
                  {user.subscriptionDaysLeft > 365 ? '∞' : user.subscriptionDaysLeft}
                </div>
                <div className="text-sm text-[#8B8279]">
                  {user.subscriptionDaysLeft > 365 ? 'безлимит' : 'дней осталось'}
                </div>
              </div>
              
              {/* Прогресс-бар */}
              <div className="mb-4">
                <div className="h-2 bg-[#F5E6D3] rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-gradient-to-r from-[#B08968] to-[#C9A882] rounded-full transition-all duration-500"
                    style={{ width: `${Math.min((user.subscriptionDaysLeft / user.subscriptionTotal) * 100, 100)}%` }}
                  ></div>
                </div>
              </div>
              
              <a 
                href="https://t.me/momsclubsubscribe_bot?start=renew" 
                target="_blank"
                className="block w-full text-center py-3 bg-gradient-to-r from-[#B08968] to-[#A67C52] text-white font-semibold rounded-xl hover:shadow-lg transition-all duration-300 text-sm"
              >
                Продлить подписку
              </a>
            </div>
          </div>
        </div>

        {/* Цитата дня */}
        <QuoteOfDay />

        {/* ⭐ Компактная секция "Выбор Полины" */}
        {materials.filter(m => m.is_featured).length > 0 && (
          <div className="mb-6">
            <h3 className="text-lg font-bold text-[#2D2A26] flex items-center gap-2 mb-3">
              <span>⭐</span> Выбор Полины
            </h3>
            <div className="flex gap-3 overflow-x-auto pb-2 -mx-4 px-4 scrollbar-hide">
              {materials.filter(m => m.is_featured).map((material) => (
                <div 
                  key={material.id}
                  onClick={() => openMaterial(material)}
                  className="flex-shrink-0 w-40 bg-gradient-to-br from-amber-50 to-orange-50 rounded-xl p-3 border border-amber-200/50 hover:shadow-lg hover:-translate-y-0.5 transition-all cursor-pointer"
                >
                  {material.cover_image ? (
                    <img src={material.cover_image} alt={material.title} className="w-full h-20 object-cover rounded-lg mb-2" />
                  ) : (
                    <div className="w-full h-20 bg-gradient-to-br from-amber-200 to-amber-300 rounded-lg mb-2 flex items-center justify-center text-2xl">
                      {material.categories?.[0]?.icon || material.category?.icon || '⭐'}
                    </div>
                  )}
                  <h4 className="font-medium text-[#2D2A26] text-xs line-clamp-2 leading-tight">{material.title}</h4>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 🤖 Секция "Вам понравится" — AI рекомендации */}
        {recommendations.materials.length > 0 && (
          <div className="mb-6">
            <h3 className="text-lg font-bold text-[#2D2A26] flex items-center gap-2 mb-3">
              <span>✨</span> {recommendations.title}
              {recommendations.type === 'personalized' && (
                <span className="text-xs font-normal text-[#B08968] bg-[#F5E6D3] px-2 py-0.5 rounded-full">AI</span>
              )}
            </h3>
            <div className="flex gap-3 overflow-x-auto pb-2 -mx-4 px-4 scrollbar-hide">
              {recommendations.materials.map((material) => (
                <div 
                  key={material.id}
                  onClick={() => openMaterial(material)}
                  className="flex-shrink-0 w-40 bg-gradient-to-br from-purple-50 to-pink-50 rounded-xl p-3 border border-purple-200/50 hover:shadow-lg hover:-translate-y-0.5 transition-all cursor-pointer"
                >
                  {material.cover_image ? (
                    <img src={material.cover_image} alt={material.title} className="w-full h-20 object-cover rounded-lg mb-2" />
                  ) : (
                    <div className="w-full h-20 bg-gradient-to-br from-purple-200 to-pink-200 rounded-lg mb-2 flex items-center justify-center text-2xl">
                      {(material as unknown as {icon?: string}).icon || material.categories?.[0]?.icon || material.category?.icon || '✨'}
                    </div>
                  )}
                  <h4 className="font-medium text-[#2D2A26] text-xs line-clamp-2 leading-tight">{material.title}</h4>
                  <p className="text-[10px] text-[#8B8279] mt-1">{(material as unknown as {category_name?: string}).category_name || material.categories?.[0]?.name || material.category?.name}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Фильтры категорий */}
        <CategoryFilter 
          categories={apiCategories}
          activeCategory={activeCategory}
          featuredCount={materials.filter(m => m.is_featured).length}
          onChange={setActiveCategory}
        />

        {/* 🔍 Поиск + Прогресс */}
        <div className="mb-6 grid lg:grid-cols-4 gap-4">
          {/* Поиск */}
          <div className="lg:col-span-3 relative">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="🔍 Поиск материалов..."
              className="w-full px-5 py-3 lg:px-6 lg:py-4 rounded-xl lg:rounded-2xl bg-white/90 border border-[#E8D4BA]/40 focus:border-[#B08968] focus:outline-none focus:ring-2 focus:ring-[#B08968]/20 text-[#2D2A26] placeholder-[#A09890] shadow-lg shadow-[#C9A882]/5 transition-all"
            />
            {searchQuery && (
              <button 
                onClick={() => setSearchQuery('')}
                className="absolute right-3 lg:right-4 top-1/2 -translate-y-1/2 text-[#8B8279] hover:text-[#B08968] text-lg"
              >
                ✕
              </button>
            )}
          </div>
          
          {/* Прогресс изучения — только десктоп */}
          <div className="hidden lg:block bg-white/90 rounded-2xl p-4 border border-[#E8D4BA]/40 shadow-lg shadow-[#C9A882]/5">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-[#8B8279]">📚 Изучено материалов</span>
              <span className="text-xs font-bold text-[#B08968]">{user.totalMaterials > 0 ? Math.round((user.uniqueViewed / user.totalMaterials) * 100) : 0}%</span>
            </div>
            <div className="h-2 bg-[#F5E6D3] rounded-full overflow-hidden">
              <div 
                className="h-full bg-gradient-to-r from-[#B08968] to-[#C9A882] rounded-full transition-all duration-500"
                style={{ width: `${user.totalMaterials > 0 ? Math.min((user.uniqueViewed / user.totalMaterials) * 100, 100) : 0}%` }}
              ></div>
            </div>
            <div className="text-xs text-[#8B8279] mt-1">{user.uniqueViewed} из {user.totalMaterials || 0}</div>
          </div>
        </div>
        
        {/* Результаты поиска */}
        {searchQuery && (
          <p className="text-sm text-[#8B8279] mb-4 -mt-2">
            🔍 Найдено: {materials.filter(m => 
              m.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
              m.description?.toLowerCase().includes(searchQuery.toLowerCase())
            ).length} материалов
          </p>
        )}

        {/* �� Материалы */}
        <section className="mb-12">
          {(() => {
            const filteredMaterials = materials
              .filter(m => {
                if (activeCategory === 'all') return true
                if (activeCategory === 'featured') return m.is_featured
                // Проверяем новый массив categories или старое поле category
                if (m.categories?.length) {
                  return m.categories.some(c => c.slug === activeCategory)
                }
                return m.category?.slug === activeCategory
              })
              .filter(m => {
                if (!searchQuery.trim()) return true
                const query = searchQuery.toLowerCase()
                const categoryNames = m.categories?.map(c => c.name.toLowerCase()).join(' ') || m.category?.name.toLowerCase() || ''
                return (
                  m.title.toLowerCase().includes(query) ||
                  m.description?.toLowerCase().includes(query) ||
                  categoryNames.includes(query)
                )
              })
            
            return (
              <>
                <div className="flex items-center justify-between mb-6">
                  <div className="flex items-center space-x-3">
                    <h3 className="text-2xl font-bold text-[#2D2A26]">
                      {searchQuery ? '🔍 Результаты поиска' : '📚 Материалы'}
                    </h3>
                    <span className="text-xs bg-green-100 text-green-700 px-2 py-1 rounded-full font-semibold">
                      {filteredMaterials.length} шт.
                    </span>
                  </div>
                </div>
                
                {filteredMaterials.length === 0 ? (
                  <div className="text-center py-12 bg-white/80 rounded-2xl border border-[#E8D4BA]/40">
                    <div className="text-4xl mb-4">{searchQuery ? '🔍' : '📭'}</div>
                    <p className="text-[#8B8279] mb-2">
                      {searchQuery ? `Ничего не найдено по запросу "${searchQuery}"` : 'Пока нет материалов'}
                    </p>
                    {searchQuery && (
                      <button 
                        onClick={() => setSearchQuery('')}
                        className="text-[#B08968] hover:underline text-sm"
                      >
                        Сбросить поиск
                      </button>
                    )}
                  </div>
                ) : (
                  <>
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                      {filteredMaterials.slice(0, visibleCount).map((material, index) => (
                        <div 
                          key={material.id} 
                          className="group bg-white/90 rounded-2xl shadow-lg shadow-[#C9A882]/10 hover:shadow-xl hover:shadow-[#C9A882]/20 transition-all duration-500 p-5 cursor-pointer border border-[#E8D4BA]/40 hover:-translate-y-1 relative overflow-hidden animate-fadeIn"
                          style={{ animationDelay: `${(index % ITEMS_PER_PAGE) * 80}ms` }}
                        >
                          {/* Бейджи */}
                          <div className="absolute top-3 right-3 flex gap-1.5 z-10">
                            {material.is_featured && (
                              <div className="bg-gradient-to-r from-amber-400 to-amber-500 text-white text-xs font-bold px-2 py-1 rounded-lg shadow-md">
                                ⭐ Выбор Полины
                              </div>
                            )}
                            {new Date(material.created_at) > new Date(Date.now() - 7 * 24 * 60 * 60 * 1000) && (
                              <div className="bg-green-500 text-white text-xs font-bold px-2 py-1 rounded-lg">NEW</div>
                            )}
                          </div>
                          <button
                            onClick={(e) => { e.stopPropagation(); toggleFavorite(material.id) }}
                            className={`absolute bottom-2 right-2 z-20 w-8 h-8 rounded-full flex items-center justify-center transition-all shadow-md ${favoriteIds.has(material.id) ? 'bg-red-500 text-white' : 'bg-white/90 text-gray-400 hover:bg-red-100 hover:text-red-500'}`}
                          >
                            <span className="text-base">{favoriteIds.has(material.id) ? '❤️' : '🤍'}</span>
                          </button>
                          <div onClick={() => openMaterial(material)}>
                            {material.cover_image ? (
                              <img src={material.cover_image} alt={material.title} className="w-full h-24 object-cover rounded-xl mb-3" />
                            ) : (
                              <div className="w-full h-24 bg-gradient-to-br from-[#C9A882] to-[#B08968] rounded-xl mb-3 flex items-center justify-center text-3xl">{material.categories?.[0]?.icon || material.category?.icon || '📄'}</div>
                            )}
                            <span className="text-xs bg-[#F5E6D3] text-[#8B7355] px-2 py-1 rounded-full font-medium truncate max-w-full block">
                              {material.categories?.length ? material.categories.slice(0, 2).map(c => c.name).join(' • ') : (material.category?.name || material.format || 'Материал')}
                            </span>
                            <h4 className="font-semibold text-[#2D2A26] mt-2 text-sm leading-tight line-clamp-2">{material.title}</h4>
                            {material.description && <p className="text-xs text-[#8B8279] mt-1 line-clamp-2">{material.description}</p>}
                            <div className="text-xs text-[#8B8279] mt-2 flex items-center gap-3">
                              <span className="flex items-center gap-1">
                                <span>👁️</span>
                                <span>{material.views}</span>
                              </span>
                              {(material.favorites_count ?? 0) > 0 && (
                                <span className="flex items-center gap-1 text-[#B08968]">
                                  <span>❤️</span>
                                  <span>{material.favorites_count}</span>
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                    
                    {/* Кнопки "Показать ещё" / "Скрыть" */}
                    {filteredMaterials.length > ITEMS_PER_PAGE && (
                      <div className="flex justify-center gap-3 mt-6">
                        {visibleCount < filteredMaterials.length && (
                          <button
                            onClick={() => setVisibleCount(prev => prev + ITEMS_PER_PAGE)}
                            className="px-6 py-3 bg-gradient-to-r from-[#B08968] to-[#A67C52] text-white font-medium rounded-xl shadow-lg shadow-[#B08968]/25 hover:shadow-xl hover:-translate-y-0.5 transition-all duration-300"
                          >
                            Показать ещё ({Math.min(ITEMS_PER_PAGE, filteredMaterials.length - visibleCount)})
                          </button>
                        )}
                        {visibleCount > ITEMS_PER_PAGE && (
                          <button
                            onClick={() => setVisibleCount(ITEMS_PER_PAGE)}
                            className="px-6 py-3 bg-white/90 text-[#5C5650] font-medium rounded-xl border border-[#E8D4BA]/40 hover:bg-[#F5E6D3] hover:-translate-y-0.5 transition-all duration-300"
                          >
                            Скрыть
                          </button>
                        )}
                      </div>
                    )}
                  </>
                )}
              </>
            )
          })()}
        </section>

        {/* Категории из API */}
        {apiCategories.length > 0 && (
          <section className="mb-12">
            <h3 className="text-2xl font-bold text-[#2D2A26] mb-6">📂 Категории</h3>
            
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {apiCategories.map((cat) => (
                <button 
                  key={cat.id}
                  onClick={() => setActiveCategory(cat.slug)}
                  className={`group bg-white/90 rounded-2xl p-6 text-center shadow-lg shadow-[#C9A882]/10 hover:shadow-xl hover:shadow-[#C9A882]/20 transition-all duration-300 cursor-pointer border hover:-translate-y-1 ${
                    activeCategory === cat.slug 
                      ? 'border-[#B08968] bg-[#F5E6D3]/50' 
                      : 'border-[#E8D4BA]/40'
                  }`}
                >
                  <div className="text-4xl mb-3 group-hover:scale-110 transition-transform duration-300">{cat.icon}</div>
                  <div className="font-semibold text-[#2D2A26]">{cat.name}</div>
                  <div className="text-sm text-[#8B8279] mt-2">
                    {cat.materials_count || 0} материалов
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}

      </main>

      {/* Push Promo Modal */}
      <PushPromoModal 
        isOpen={showPushPromo} 
        onEnable={async () => {
          setShowPushPromo(false)
          return await togglePush()
        }}
        onDismiss={() => setShowPushPromo(false)}
      />

      {/* Mobile Navigation */}
      <MobileNav activePage="library" isPWA={isPWA} isVisible={showMobileNav} />
    </div>
  )
}
