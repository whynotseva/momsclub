'use client'

// Локальный тип для материала (совместим с разными источниками)
interface MaterialData {
  id: number
  title: string
  description?: string
  external_url?: string
  cover_image?: string
  cover_url?: string  // Оптимизированный URL обложки
  is_featured?: boolean
  is_published?: boolean
  views: number
  favorites_count?: number
  created_at: string
  category?: { name: string; slug: string; icon: string }
  categories?: { id?: number; name: string; slug: string; icon: string }[]
  category_id?: number
  category_ids?: number[]
  format?: string
}

interface MaterialCardProps {
  material: MaterialData
  isFavorite: boolean
  isNew?: boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onOpen: (material: any) => void
  onToggleFavorite: (materialId: number) => void
  animationDelay?: number
}

/**
 * Карточка материала
 */
export function MaterialCard({
  material,
  isFavorite,
  isNew = false,
  onOpen,
  onToggleFavorite,
  animationDelay = 0,
}: MaterialCardProps) {
  const categoryIcon = material.categories?.[0]?.icon || material.category?.icon || '📄'
  const categoryName = material.categories?.length
    ? material.categories.map(c => c.name).join(' • ')
    : material.category?.name || material.format || 'Материал'

  return (
    <div
      className="group bg-white/90 rounded-2xl shadow-lg shadow-[#C9A882]/10 hover:shadow-xl hover:shadow-[#C9A882]/20 transition-all duration-500 p-5 cursor-pointer border border-[#E8D4BA]/40 hover:-translate-y-1 relative overflow-hidden animate-fadeIn"
      style={{ animationDelay: `${animationDelay}ms` }}
    >
      {/* Бейджи */}
      <div className="absolute top-3 right-3 flex gap-1.5 z-10">
        {material.is_featured && (
          <div className="bg-gradient-to-r from-amber-400 to-amber-500 text-white text-xs font-bold px-2 py-1 rounded-lg shadow-md">
            ⭐ Выбор Полины
          </div>
        )}
        {isNew && (
          <div className="bg-green-500 text-white text-xs font-bold px-2 py-1 rounded-lg">NEW</div>
        )}
      </div>

      {/* Кнопка избранного */}
      <button
        onClick={(e) => {
          e.stopPropagation()
          onToggleFavorite(material.id)
        }}
        className={`absolute bottom-2 right-2 z-20 w-8 h-8 rounded-full flex items-center justify-center transition-all shadow-md ${
          isFavorite
            ? 'bg-red-500 text-white'
            : 'bg-white/90 text-gray-400 hover:bg-red-100 hover:text-red-500'
        }`}
      >
        <span className="text-base">{isFavorite ? '❤️' : '🤍'}</span>
      </button>

      {/* Контент карточки */}
      <div onClick={() => onOpen(material)}>
        {(material.cover_url || material.cover_image) ? (
          <img
            src={material.cover_url || material.cover_image}
            alt={material.title}
            className="w-full h-24 object-cover rounded-xl mb-3"
          />
        ) : (
          <div className="w-full h-24 bg-gradient-to-br from-[#C9A882] to-[#B08968] rounded-xl mb-3 flex items-center justify-center text-3xl">
            {categoryIcon}
          </div>
        )}

        <span className="text-xs bg-[#F5E6D3] text-[#8B7355] px-2 py-1 rounded-full font-medium inline-block max-w-full truncate" title={categoryName}>
          {categoryName}
        </span>

        <h4 className="font-semibold text-[#2D2A26] mt-2 text-sm leading-tight line-clamp-2">
          {material.title}
        </h4>

        {material.description && (
          <p className="text-xs text-[#8B8279] mt-1 line-clamp-2">{material.description}</p>
        )}

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
  )
}
