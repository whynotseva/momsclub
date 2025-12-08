'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { api } from '@/lib/api'
import { usePresence } from '@/hooks/usePresence'
import { usePushNotifications } from '@/hooks/usePushNotifications'
import { QuoteOfDay, MobileNav, PushPromoModal, CategoryFilter, SubscriptionCard, MaterialCard, Header, FeaturedSection, WelcomeCard, SearchBar } from '@/components/library'
import { ADMIN_IDS, DEFAULT_USER, LOYALTY_BADGES } from '@/lib/constants'

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
  const [user, setUser] = useState(DEFAULT_USER)
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

      {/* Header */}
      <Header
        user={{ name: user.name, avatar: user.avatar, notifications: user.notifications }}
        isAdmin={isAdmin}
        isVisible={showHeader}
        notifications={notifications}
        showNotifications={showNotifications}
        showProfileMenu={showProfileMenu}
        pushSupported={pushSupported}
        pushSubscribed={pushSubscribed}
        pushLoading={pushLoading}
        onToggleNotifications={() => setShowNotifications(!showNotifications)}
        onToggleProfileMenu={() => setShowProfileMenu(!showProfileMenu)}
        onTogglePush={togglePush}
        onMarkAsRead={markAsRead}
        onMarkAllAsRead={markAllAsRead}
        onLogout={() => {
          localStorage.removeItem('access_token')
          localStorage.removeItem('user')
          sessionStorage.removeItem('auth_error')
          router.push('/login')
        }}
      />

      {/* Main Content — с отступом под fixed header */}
      <main className="max-w-7xl mx-auto px-4 py-8" style={{ paddingTop: 'calc(5rem + env(safe-area-inset-top, 0px))' }}>
        {/* Приветствие + Профиль */}
        <div className="mb-10 grid lg:grid-cols-3 gap-6">
          {/* Приветствие */}
          <WelcomeCard
            userName={user.name}
            materialsViewed={user.materialsViewed}
            favorites={user.favorites}
            uniqueViewed={user.uniqueViewed}
            totalMaterials={user.totalMaterials}
            loyaltyLevel={user.loyaltyLevel}
            loyaltyBadges={LOYALTY_BADGES}
          />
          
          {/* Карточка подписки */}
          <SubscriptionCard daysLeft={user.subscriptionDaysLeft} total={user.subscriptionTotal} />
        </div>

        {/* Цитата дня */}
        <QuoteOfDay />

        {/* ⭐ Выбор Полины */}
        <FeaturedSection
          title="Выбор Полины"
          icon="⭐"
          materials={materials.filter(m => m.is_featured)}
          gradientFrom="from-amber-50"
          gradientTo="to-orange-50"
          borderColor="border-amber-200/50"
          onMaterialClick={openMaterial}
        />

        {/* ✨ Вам понравится — AI рекомендации */}
        <FeaturedSection
          title={recommendations.title}
          icon="✨"
          badge={recommendations.type === 'personalized' ? 'AI' : undefined}
          materials={recommendations.materials}
          gradientFrom="from-purple-50"
          gradientTo="to-pink-50"
          borderColor="border-purple-200/50"
          onMaterialClick={openMaterial}
        />

        {/* Фильтры категорий */}
        <CategoryFilter 
          categories={apiCategories}
          activeCategory={activeCategory}
          featuredCount={materials.filter(m => m.is_featured).length}
          onChange={setActiveCategory}
        />

        {/* 🔍 Поиск + Прогресс */}
        <SearchBar
          value={searchQuery}
          onChange={setSearchQuery}
          uniqueViewed={user.uniqueViewed}
          totalMaterials={user.totalMaterials}
        />
        
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
                        <MaterialCard
                          key={material.id}
                          material={material}
                          isFavorite={favoriteIds.has(material.id)}
                          isNew={new Date(material.created_at) > new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)}
                          onOpen={openMaterial}
                          onToggleFavorite={toggleFavorite}
                          animationDelay={(index % ITEMS_PER_PAGE) * 80}
                        />
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
