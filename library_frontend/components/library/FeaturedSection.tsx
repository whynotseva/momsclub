'use client'

interface MaterialItem {
  id: number
  title: string
  cover_image?: string
  cover_url?: string  // Оптимизированный URL обложки
  category?: { name: string; icon: string }
  categories?: { name: string; icon: string }[]
}

interface FeaturedSectionProps {
  title: string
  icon: string
  badge?: string
  materials: MaterialItem[]
  gradientFrom: string
  gradientTo: string
  borderColor: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onMaterialClick: (material: any) => void
}

/**
 * Универсальная секция с горизонтальным скроллом материалов
 */
export function FeaturedSection({
  title,
  icon,
  badge,
  materials,
  gradientFrom,
  gradientTo,
  borderColor,
  onMaterialClick,
}: FeaturedSectionProps) {
  if (materials.length === 0) return null

  return (
    <div className="mb-6">
      <h3 className="text-lg font-bold text-[#2D2A26] flex items-center gap-2 mb-3">
        <span>{icon}</span> {title}
        {badge && (
          <span className="text-xs font-normal text-[#B08968] bg-[#F5E6D3] px-2 py-0.5 rounded-full">{badge}</span>
        )}
      </h3>
      <div className="flex gap-3 overflow-x-auto pb-2 -mx-4 px-4 scrollbar-hide">
        {materials.map((material) => (
          <div 
            key={material.id}
            onClick={() => onMaterialClick(material)}
            className={`flex-shrink-0 w-40 bg-gradient-to-br ${gradientFrom} ${gradientTo} rounded-xl p-3 border ${borderColor} hover:shadow-lg hover:-translate-y-0.5 transition-all cursor-pointer`}
          >
            {(material.cover_url || material.cover_image) ? (
              <img src={material.cover_url || material.cover_image} alt={material.title} className="w-full h-20 object-cover rounded-lg mb-2" />
            ) : (
              <div className={`w-full h-20 bg-gradient-to-br ${gradientFrom.replace('50', '200')} ${gradientTo.replace('50', '300')} rounded-lg mb-2 flex items-center justify-center text-2xl`}>
                {material.categories?.[0]?.icon || material.category?.icon || icon}
              </div>
            )}
            <h4 className="font-medium text-[#2D2A26] text-xs line-clamp-2 leading-tight">{material.title}</h4>
          </div>
        ))}
      </div>
    </div>
  )
}
