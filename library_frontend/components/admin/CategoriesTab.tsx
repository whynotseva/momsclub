'use client'

interface Category {
  id: number
  name: string
  slug: string
  icon: string
  description?: string
}

interface CategoriesTabProps {
  categories: Category[]
  onOpenForm: (category?: Category) => void
  onDelete: (id: number) => void
}

/**
 * Таб управления категориями в админке
 */
export function CategoriesTab({ categories, onOpenForm, onDelete }: CategoriesTabProps) {
  return (
    <div>
      {/* Кнопка добавления */}
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-lg font-semibold text-[#5D4E3A] dark:text-[#E5E5E5]">
          Категории ({categories.length})
        </h2>
        <button
          onClick={() => onOpenForm()}
          className="px-5 py-2.5 bg-gradient-to-r from-[#C9A882] to-[#B08968] text-white rounded-xl font-medium hover:shadow-lg transition-all flex items-center gap-2"
        >
          <span>➕</span> Добавить категорию
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {categories.map(category => (
          <div 
            key={category.id}
            className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-2xl p-5 border border-[#E8D4BA]/30 dark:border-[#3D3D3D] hover:shadow-lg transition-all"
          >
            <div className="flex items-center gap-3 mb-3">
              <div className="w-12 h-12 bg-gradient-to-br from-[#F5E6D3] to-[#E8D4BA] dark:from-[#2A2A2A] dark:to-[#3D3D3D] rounded-xl flex items-center justify-center">
                <span className="text-2xl">{category.icon}</span>
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="font-medium text-[#5D4E3A] dark:text-[#E5E5E5] truncate">{category.name}</h3>
                <p className="text-xs text-[#8B8279] dark:text-[#707070]">/{category.slug}</p>
              </div>
            </div>
            {category.description && (
              <p className="text-sm text-[#8B8279] dark:text-[#707070] mb-3 line-clamp-2">{category.description}</p>
            )}
            <div className="flex gap-2">
              <button 
                onClick={() => onOpenForm(category)}
                className="flex-1 px-3 py-2 text-sm text-[#B08968] bg-[#F5E6D3]/50 dark:bg-[#2A2A2A] rounded-lg hover:bg-[#F5E6D3] dark:hover:bg-[#3D3D3D] transition-colors"
              >
                ✏️ Редактировать
              </button>
              <button 
                onClick={() => onDelete(category.id)}
                className="px-3 py-2 text-sm text-red-500 dark:text-red-400 bg-red-50 dark:bg-red-900/30 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/50 transition-colors"
              >
                🗑️
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
