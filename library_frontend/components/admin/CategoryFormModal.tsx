'use client'

interface Category {
  id: number
  name: string
  slug: string
  icon: string
  description?: string
}

interface CategoryForm {
  icon: string
  name: string
  slug: string
  description: string
}

interface CategoryFormModalProps {
  isOpen: boolean
  editingCategory: Category | null
  categoryForm: CategoryForm
  onClose: () => void
  onSubmit: (e: React.FormEvent) => void
  onFormChange: (form: CategoryForm) => void
}

const EMOJI_OPTIONS = ['📚', '🎬', '💡', '📱', '✨', '🏆', '🎙️', '🤝', '📝', '🎨', '💼', '🌟', '🎯', '💎', '🔥', '💕']

/**
 * Модалка создания/редактирования категории
 */
export function CategoryFormModal({
  isOpen,
  editingCategory,
  categoryForm,
  onClose,
  onSubmit,
  onFormChange,
}: CategoryFormModalProps) {
  if (!isOpen) return null

  const handleNameChange = (name: string) => {
    const slug = name.toLowerCase()
      .replace(/[^\w\sа-яё-]/gi, '')
      .replace(/\s+/g, '-')
      .replace(/[а-яё]/g, c => {
        const map: Record<string, string> = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'}
        return map[c] || c
      })
    onFormChange({...categoryForm, name, slug})
  }

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-end sm:items-center justify-center pt-16 sm:pt-0 sm:p-4 overscroll-none touch-none">
      <div className="bg-white rounded-t-3xl sm:rounded-3xl w-full sm:max-w-md h-[85vh] sm:h-auto sm:max-h-[85vh] flex flex-col overflow-hidden touch-auto">
        {/* Индикатор для мобильных */}
        <div className="sm:hidden flex justify-center pt-3 pb-2 shrink-0">
          <div className="w-10 h-1 bg-[#E8D4BA] rounded-full"></div>
        </div>
        
        <div className="border-b border-[#E8D4BA]/30 px-4 sm:px-6 py-3 sm:py-4 shrink-0">
          <h2 className="text-lg sm:text-xl font-bold text-[#5D4E3A] text-center sm:text-left">
            {editingCategory ? 'Редактировать категорию' : 'Новая категория'}
          </h2>
        </div>
        
        <form id="category-form" onSubmit={onSubmit} className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4">
          {/* Иконка */}
          <div>
            <label className="block text-sm font-medium text-[#5D4E3A] mb-1.5">
              Иконка (эмодзи)
            </label>
            
            {/* Быстрый выбор */}
            <div className="flex flex-wrap gap-1.5 mb-3">
              {EMOJI_OPTIONS.map(emoji => (
                <button
                  key={emoji}
                  type="button"
                  onClick={() => onFormChange({...categoryForm, icon: emoji})}
                  className={`w-10 h-10 rounded-xl text-xl hover:bg-[#F5E6D3] transition-all ${
                    categoryForm.icon === emoji 
                      ? 'bg-gradient-to-br from-[#C9A882] to-[#B08968] shadow-md scale-110' 
                      : 'bg-[#F5E6D3]/50'
                  }`}
                >
                  {emoji}
                </button>
              ))}
            </div>

            {/* Свой эмодзи */}
            <div className="flex items-center gap-3 p-3 bg-[#F5E6D3]/30 rounded-xl">
              <div className="w-14 h-14 bg-white border-2 border-dashed border-[#E8D4BA] rounded-xl flex items-center justify-center">
                <span className="text-3xl">{categoryForm.icon || '?'}</span>
              </div>
              <div className="flex-1">
                <label className="block text-xs text-[#8B8279] mb-1">Или введи свой эмодзи:</label>
                <input
                  type="text"
                  value={categoryForm.icon}
                  onChange={e => onFormChange({...categoryForm, icon: e.target.value})}
                  className="w-full px-3 py-2 border border-[#E8D4BA]/50 rounded-lg text-center text-xl focus:ring-2 focus:ring-[#B08968]/30 focus:border-[#B08968] outline-none bg-white"
                  placeholder="🎉"
                  maxLength={2}
                />
              </div>
            </div>
          </div>

          {/* Название */}
          <div>
            <label className="block text-sm font-medium text-[#5D4E3A] mb-1.5">
              Название *
            </label>
            <input
              type="text"
              value={categoryForm.name}
              onChange={e => handleNameChange(e.target.value)}
              className="w-full px-4 py-3 border border-[#E8D4BA]/50 rounded-xl focus:ring-2 focus:ring-[#B08968]/30 focus:border-[#B08968] outline-none"
              placeholder="Название категории"
              required
            />
          </div>

          {/* Slug */}
          <div>
            <label className="block text-sm font-medium text-[#5D4E3A] mb-1.5">
              URL-адрес (slug)
            </label>
            <div className="flex items-center">
              <span className="text-[#8B8279] mr-1">/</span>
              <input
                type="text"
                value={categoryForm.slug}
                onChange={e => onFormChange({...categoryForm, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '')})}
                className="flex-1 px-3 py-3 border border-[#E8D4BA]/50 rounded-xl focus:ring-2 focus:ring-[#B08968]/30 focus:border-[#B08968] outline-none font-mono text-sm"
                placeholder="url-kategorii"
              />
            </div>
          </div>

          {/* Описание */}
          <div>
            <label className="block text-sm font-medium text-[#5D4E3A] mb-1.5">
              Описание (опционально)
            </label>
            <textarea
              value={categoryForm.description}
              onChange={e => onFormChange({...categoryForm, description: e.target.value})}
              className="w-full px-4 py-3 border border-[#E8D4BA]/50 rounded-xl focus:ring-2 focus:ring-[#B08968]/30 focus:border-[#B08968] outline-none resize-none"
              rows={2}
              placeholder="Краткое описание категории..."
            />
          </div>
        </form>
        
        {/* Кнопки */}
        <div className="flex gap-3 p-4 sm:p-6 border-t border-[#E8D4BA]/30 bg-white shrink-0" style={{ paddingBottom: 'max(16px, env(safe-area-inset-bottom))' }}>
          <button
            type="button"
            onClick={onClose}
            className="flex-1 px-5 py-3 border border-[#E8D4BA] text-[#8B8279] rounded-xl font-medium hover:bg-[#F5E6D3]/50 transition-all"
          >
            Отмена
          </button>
          <button
            type="submit"
            form="category-form"
            className="flex-1 px-5 py-3 bg-gradient-to-r from-[#C9A882] to-[#B08968] text-white rounded-xl font-medium hover:shadow-lg transition-all"
          >
            {editingCategory ? 'Сохранить' : 'Создать'}
          </button>
        </div>
      </div>
    </div>
  )
}
