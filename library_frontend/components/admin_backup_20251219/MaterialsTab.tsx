'use client'

import { useState, useMemo } from 'react'

interface Category {
  id: number
  name: string
  slug: string
  icon: string
}

interface Material {
  id: number
  title: string
  description?: string
  external_url?: string
  category_id?: number
  category_ids: number[]
  categories?: Category[]
  format: string
  cover_image?: string
  is_published: boolean
  is_featured: boolean
  created_at: string
  views: number
}

interface MaterialsTabProps {
  materials: Material[]
  categories: Category[]
  loadingMaterials: boolean
  onOpenForm: () => void
  onEdit: (material: Material) => void
  onDelete: (id: number) => void
  onTogglePublish: (material: Material) => void
}

/**
 * Таб управления материалами в админке
 */
export function MaterialsTab({
  materials,
  categories,
  loadingMaterials,
  onOpenForm,
  onEdit,
  onDelete,
  onTogglePublish
}: MaterialsTabProps) {
  const [materialsSearch, setMaterialsSearch] = useState('')
  const [materialsLimit, setMaterialsLimit] = useState(10)

  const filteredMaterials = useMemo(() => {
    return materials.filter(m => 
      m.title.toLowerCase().includes(materialsSearch.toLowerCase()) ||
      m.description?.toLowerCase().includes(materialsSearch.toLowerCase())
    )
  }, [materials, materialsSearch])

  const displayedMaterials = useMemo(() => {
    return filteredMaterials.slice(0, materialsLimit)
  }, [filteredMaterials, materialsLimit])

  const getCategoryNames = (material: Material) => {
    if (material.category_ids?.length > 0) {
      return categories.filter(c => material.category_ids.includes(c.id)).map(c => c.name).join(' • ')
    }
    if (material.category_id) {
      return categories.find(c => c.id === material.category_id)?.name || '-'
    }
    return '-'
  }

  return (
    <div>
      {/* Action bar */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-4 sm:mb-6 gap-3">
        <h2 className="text-base sm:text-lg font-semibold text-[#5D4E3A]">
          Все материалы ({materials.length})
        </h2>
        <div className="flex gap-2 w-full sm:w-auto">
          {/* Поиск */}
          <div className="relative flex-1 sm:flex-initial">
            <input
              type="text"
              value={materialsSearch}
              onChange={(e) => {
                setMaterialsSearch(e.target.value)
                setMaterialsLimit(10)
              }}
              placeholder="🔍 Поиск..."
              className="w-full sm:w-48 px-3 py-2 border border-[#E8D4BA]/50 rounded-lg text-sm focus:ring-2 focus:ring-[#B08968]/30 focus:border-[#B08968] outline-none"
            />
            {materialsSearch && (
              <button
                onClick={() => setMaterialsSearch('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[#8B8279] hover:text-[#5D4E3A]"
              >
                ✕
              </button>
            )}
          </div>
          <button
            onClick={onOpenForm}
            className="px-3 sm:px-5 py-2 sm:py-2.5 bg-gradient-to-r from-[#C9A882] to-[#B08968] text-white rounded-lg sm:rounded-xl text-sm sm:text-base font-medium hover:shadow-lg transition-all flex items-center gap-1.5 sm:gap-2 whitespace-nowrap"
          >
            <span>➕</span> <span className="hidden sm:inline">Новый</span>
          </button>
        </div>
      </div>

      {/* Materials list */}
      {loadingMaterials ? (
        <div className="bg-white/80 backdrop-blur-xl rounded-2xl p-8 border border-[#E8D4BA]/30">
          <div className="animate-pulse space-y-4">
            {[1, 2, 3, 4].map(i => (
              <div key={i} className="flex items-center gap-4 p-4 bg-[#F5E6D3]/30 rounded-xl">
                <div className="h-4 bg-[#E8D4BA]/50 rounded w-1/3"></div>
                <div className="h-4 bg-[#E8D4BA]/30 rounded w-1/6"></div>
                <div className="h-4 bg-[#E8D4BA]/30 rounded w-1/6"></div>
              </div>
            ))}
          </div>
        </div>
      ) : filteredMaterials.length === 0 ? (
        <div className="bg-white/80 backdrop-blur-xl rounded-2xl p-12 border border-[#E8D4BA]/30 text-center">
          <div className="w-16 h-16 bg-[#F5E6D3] rounded-2xl flex items-center justify-center mx-auto mb-4">
            <span className="text-3xl">{materialsSearch ? '🔍' : '📚'}</span>
          </div>
          <h3 className="text-lg font-medium text-[#5D4E3A] mb-2">
            {materialsSearch ? 'Ничего не найдено' : 'Пока нет материалов'}
          </h3>
          <p className="text-[#8B8279] mb-4">
            {materialsSearch ? `По запросу "${materialsSearch}" ничего не найдено` : 'Добавьте первый материал в библиотеку'}
          </p>
          {!materialsSearch && (
            <button
              onClick={onOpenForm}
              className="px-5 py-2.5 bg-gradient-to-r from-[#C9A882] to-[#B08968] text-white rounded-xl font-medium"
            >
              Создать материал
            </button>
          )}
        </div>
      ) : (
        <>
          {/* Инфо о фильтрации */}
          {materialsSearch && (
            <p className="text-sm text-[#8B8279] mb-3">
              Найдено: {filteredMaterials.length} из {materials.length}
            </p>
          )}
          
          {/* Мобильная версия — карточки */}
          <div className="md:hidden space-y-3">
            {displayedMaterials.map(material => (
              <div key={material.id} className="bg-white/80 backdrop-blur-xl rounded-2xl border border-[#E8D4BA]/30 p-4">
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-[#5D4E3A] truncate">{material.title}</h3>
                    <p className="text-xs text-[#8B8279]">{getCategoryNames(material)}</p>
                  </div>
                  <span className={`px-2 py-1 rounded-full text-xs font-medium flex-shrink-0 ${
                    material.is_published 
                      ? 'bg-green-100 text-green-700' 
                      : 'bg-orange-100 text-orange-700'
                  }`}>
                    {material.is_published ? '✓' : '○'}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-[#8B8279]">👁 {material.views}</span>
                  <div className="flex gap-2">
                    <button
                      onClick={() => onTogglePublish(material)}
                      className={`px-3 py-1.5 text-xs rounded-lg ${
                        material.is_published 
                          ? 'text-orange-600 bg-orange-50' 
                          : 'text-green-600 bg-green-50'
                      }`}
                    >
                      {material.is_published ? 'Снять' : 'Опубл.'}
                    </button>
                    <button
                      onClick={() => onEdit(material)}
                      className="px-3 py-1.5 text-xs text-[#B08968] bg-[#F5E6D3]/50 rounded-lg"
                    >
                      ✏️
                    </button>
                    <button
                      onClick={() => onDelete(material.id)}
                      className="px-3 py-1.5 text-xs text-red-500 bg-red-50 rounded-lg"
                    >
                      🗑️
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Десктоп версия — таблица */}
          <div className="hidden md:block bg-white/80 backdrop-blur-xl rounded-2xl border border-[#E8D4BA]/30 overflow-hidden">
            <table className="w-full">
              <thead className="bg-[#F5E6D3]/50">
                <tr>
                  <th className="text-left px-4 py-3 text-sm font-medium text-[#5D4E3A]">Название</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-[#5D4E3A]">Категория</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-[#5D4E3A]">Статус</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-[#5D4E3A]">Просмотры</th>
                  <th className="text-right px-4 py-3 text-sm font-medium text-[#5D4E3A]">Действия</th>
                </tr>
              </thead>
              <tbody>
                {displayedMaterials.map(material => (
                  <tr key={material.id} className="border-t border-[#E8D4BA]/20 hover:bg-white/50">
                    <td className="px-4 py-3">
                      <div className="font-medium text-[#5D4E3A]">{material.title}</div>
                    </td>
                    <td className="px-4 py-3 text-sm text-[#8B8279]">{getCategoryNames(material)}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                        material.is_published 
                          ? 'bg-green-100 text-green-700' 
                          : 'bg-orange-100 text-orange-700'
                      }`}>
                        {material.is_published ? 'Опубликован' : 'Черновик'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-[#8B8279]">{material.views}</td>
                    <td className="px-4 py-3 text-right space-x-1">
                      <button
                        onClick={() => onTogglePublish(material)}
                        className={`px-3 py-1 text-sm rounded-lg ${
                          material.is_published 
                            ? 'text-orange-500 hover:bg-orange-50' 
                            : 'text-green-600 hover:bg-green-50'
                        }`}
                      >
                        {material.is_published ? '📤 Снять' : '✅ Опубликовать'}
                      </button>
                      <button
                        onClick={() => onEdit(material)}
                        className="px-3 py-1 text-sm text-[#B08968] hover:bg-[#F5E6D3] rounded-lg"
                      >
                        ✏️ Редактировать
                      </button>
                      <button
                        onClick={() => onDelete(material.id)}
                        className="px-3 py-1 text-sm text-red-500 hover:bg-red-50 rounded-lg"
                      >
                        🗑️ Удалить
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          
          {/* Кнопки пагинации */}
          {(filteredMaterials.length > 10 || materialsLimit > 10) && (
            <div className="flex justify-center gap-3 mt-4">
              {filteredMaterials.length > materialsLimit && (
                <button
                  onClick={() => setMaterialsLimit(prev => prev + 10)}
                  className="px-4 py-2 bg-[#F5E6D3] text-[#5D4E3A] rounded-xl text-sm font-medium hover:bg-[#E8D4BA] transition-colors"
                >
                  Показать ещё ({filteredMaterials.length - materialsLimit} осталось)
                </button>
              )}
              {materialsLimit > 10 && (
                <button
                  onClick={() => setMaterialsLimit(10)}
                  className="px-4 py-2 bg-white border border-[#E8D4BA] text-[#8B8279] rounded-xl text-sm font-medium hover:bg-[#F5E6D3] transition-colors"
                >
                  Скрыть
                </button>
              )}
            </div>
          )}
          
          {/* Счётчик */}
          <p className="text-center text-xs text-[#8B8279] mt-3">
            Показано {displayedMaterials.length} из {filteredMaterials.length}
          </p>
        </>
      )}
    </div>
  )
}
