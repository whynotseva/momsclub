'use client'

interface LoyaltyBadge {
  label: string
  color: string
  icon: string
}

interface WelcomeCardProps {
  userName: string
  materialsViewed: number
  favorites: number
  uniqueViewed: number
  totalMaterials: number
  loyaltyLevel: string
  loyaltyBadges: Record<string, LoyaltyBadge>
}

/**
 * Карточка приветствия с статистикой и статусом лояльности
 */
export function WelcomeCard({
  userName,
  materialsViewed,
  favorites,
  uniqueViewed,
  totalMaterials,
  loyaltyLevel,
  loyaltyBadges,
}: WelcomeCardProps) {
  const badge = loyaltyBadges[loyaltyLevel] || loyaltyBadges['none']
  const progressPercent = totalMaterials > 0 ? Math.min((uniqueViewed / totalMaterials) * 100, 100) : 0

  return (
    <div className="lg:col-span-2 relative">
      <div className="absolute inset-0 bg-gradient-to-r from-[#C9A882]/10 to-[#B08968]/5 rounded-3xl blur-2xl"></div>
      <div className="relative bg-white/80 backdrop-blur-sm rounded-3xl p-6 lg:p-8 border border-[#E8D4BA]/40 shadow-xl shadow-[#C9A882]/10 h-full">
        <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
          <div className="flex-1">
            <h2 className="text-xl lg:text-2xl font-bold text-[#2D2A26] mb-2">
              👋 Привет, {userName}!
            </h2>
            <p className="text-[#5C5650] text-sm lg:text-base mb-4">
              Эксклюзивные идеи для Reels, гайды и стратегии роста
            </p>
            
            {/* Статистика */}
            <div className="flex items-center gap-4 text-sm">
              <div className="flex items-center space-x-1">
                <span>👁️</span>
                <span><strong>{materialsViewed}</strong> просмотрено</span>
              </div>
              <div className="flex items-center space-x-1">
                <span>⭐</span>
                <span><strong>{favorites}</strong> в избранном</span>
              </div>
            </div>
            
            {/* Прогресс изучения — только мобильный */}
            <div className="lg:hidden mt-4 bg-[#F5E6D3]/50 rounded-xl p-3">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-medium text-[#8B8279]">📚 Изучено</span>
                <span className="text-xs font-bold text-[#B08968]">{uniqueViewed} из {totalMaterials}</span>
              </div>
              <div className="h-2 bg-white rounded-full overflow-hidden">
                <div 
                  className="h-full bg-gradient-to-r from-[#B08968] to-[#C9A882] rounded-full"
                  style={{ width: `${progressPercent}%` }}
                ></div>
              </div>
            </div>
          </div>
          
          {/* Статус лояльности */}
          <div className={`flex items-center space-x-2 px-3 py-1.5 rounded-full whitespace-nowrap text-sm ${badge.color}`}>
            <span>Статус:</span>
            <span>{badge.icon}</span>
            <span className="font-bold">{badge.label}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
