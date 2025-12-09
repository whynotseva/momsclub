'use client'

import { useEffect, useState, useMemo } from 'react'
import { usePresence } from '@/hooks/usePresence'
import { usePushNotifications } from '@/hooks/usePushNotifications'
import { useLibraryData } from '@/hooks/useLibraryData'
import { useScrollVisibility } from '@/hooks/useScrollVisibility'
import { LoadingSpinner } from '@/components/shared'
import { QuoteOfDay, MobileNav, PushPromoModal, CategoryFilter, SubscriptionCard, MaterialCard, Header, FeaturedSection, WelcomeCard, SearchBar } from '@/components/library'
import { LOYALTY_BADGES } from '@/lib/constants'

export default function LibraryPage() {
  // Основные данные из хука
  const {
    loading,
    user,
    isAdmin,
    materials,
    apiCategories,
    favoriteIds,
    notifications,
    recommendations,
    router,
    markAllAsRead,
    markAsRead,
    openMaterial,
    toggleFavorite,
  } = useLibraryData()
  
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
  const [showPushPromo, setShowPushPromo] = useState(false)
  
  // Скролл для скрытия/показа меню
  const isVisible = useScrollVisibility()
  
  // Поиск
  const [searchQuery, setSearchQuery] = useState('')
  
  // Мемоизированные фильтры
  const featuredMaterials = useMemo(() => 
    materials.filter(m => m.is_featured), 
    [materials]
  )
  
  const filteredMaterials = useMemo(() => 
    materials
      .filter(m => {
        if (activeCategory === 'all') return true
        if (activeCategory === 'featured') return m.is_featured
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
      }),
    [materials, activeCategory, searchQuery]
  )
  
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

  if (loading) {
    return <LoadingSpinner />
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
        isVisible={isVisible}
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
          materials={featuredMaterials}
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
          featuredCount={featuredMaterials.length}
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
            🔍 Найдено: {filteredMaterials.length} материалов
          </p>
        )}

        {/* 📚 Материалы */}
        <section className="mb-12">
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
      <MobileNav activePage="library" isPWA={isPWA} isVisible={isVisible} />
    </div>
  )
}
