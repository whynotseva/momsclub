'use client'

import { useState } from 'react'
import dynamic from 'next/dynamic'
import { getLinkType } from '@/lib/utils'

// Динамический импорт редактора
const RichTextEditor = dynamic(() => import('@/components/RichTextEditor'), { 
  ssr: false,
  loading: () => <div className="animate-pulse h-32 bg-gray-100 rounded-xl" />
})

interface Category {
  id: number
  name: string
  icon: string
}

interface Material {
  id: number
  title: string
  description?: string
  external_url?: string
  content?: string
  category_ids: number[]
  cover_image?: string
  is_published: boolean
  is_featured: boolean
}

interface FormData {
  title: string
  description: string
  external_url: string
  content: string
  category_ids: number[]
  format: string
  cover_image: string
  is_published: boolean
  is_featured: boolean
}

// Подкомпонент загрузки обложки
function CoverUpload({ formData, formErrors, isDragging, uploadingCover, onUpdateFormData, handleDragOver, handleDragLeave, handleDrop, onProcessImageFile }: {
  formData: FormData
  formErrors: Record<string, string>
  isDragging: boolean
  uploadingCover: boolean
  onUpdateFormData: (updates: Partial<FormData>) => void
  handleDragOver: (e: React.DragEvent) => void
  handleDragLeave: (e: React.DragEvent) => void
  handleDrop: (e: React.DragEvent) => void
  onProcessImageFile: (file: File) => void
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-[#5D4E3A] mb-1.5">Обложка *</label>
      
      {formData.cover_image && (
        <div className="relative mb-3 rounded-xl overflow-hidden bg-[#F5E6D3]">
          <img src={formData.cover_image} alt="Превью обложки" className="w-full h-48 object-cover"/>
          <button
            type="button"
            onClick={() => onUpdateFormData({ cover_image: '' })}
            className="absolute top-2 right-2 w-8 h-8 bg-black/50 hover:bg-black/70 text-white rounded-full flex items-center justify-center transition-colors"
          >
            ✕
          </button>
        </div>
      )}

      <div 
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-xl p-6 text-center transition-all cursor-pointer ${
          isDragging 
            ? 'border-[#B08968] bg-[#F5E6D3]/50 scale-[1.02]' 
            : formErrors.cover_image
              ? 'border-red-300 bg-red-50'
              : 'border-[#E8D4BA] hover:border-[#B08968] hover:bg-[#F5E6D3]/20'
        }`}
      >
        <input
          type="file"
          accept="image/*"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) onProcessImageFile(file)
          }}
          className="hidden"
          id="cover-upload"
          disabled={uploadingCover}
        />
        <label htmlFor="cover-upload" className="cursor-pointer block">
          {uploadingCover ? (
            <div className="flex items-center justify-center gap-2 text-[#8B8279]">
              <div className="w-5 h-5 border-2 border-[#B08968] border-t-transparent rounded-full animate-spin"></div>
              Загрузка...
            </div>
          ) : (
            <>
              <div className="w-14 h-14 bg-[#F5E6D3] rounded-2xl flex items-center justify-center mx-auto mb-3">
                <span className="text-2xl">📷</span>
              </div>
              <p className="text-sm font-medium text-[#5D4E3A]">Перетащите изображение сюда</p>
              <p className="text-xs text-[#8B8279] mt-1">или нажмите для выбора • JPG, PNG, WebP • до 5 МБ</p>
              <p className="text-xs text-[#B08968] mt-2 font-medium">Рекомендуемый размер: 1200 × 675 px (16:9)</p>
            </>
          )}
        </label>
      </div>
      
      {formErrors.cover_image && <p className="text-red-500 text-xs mt-2">{formErrors.cover_image}</p>}

      <div className="mt-3">
        <label className="block text-xs text-[#8B8279] mb-1">Или вставьте URL изображения:</label>
        <input
          type="url"
          value={formData.cover_image.startsWith('data:') ? '' : formData.cover_image}
          onChange={e => onUpdateFormData({ cover_image: e.target.value })}
          className="w-full px-3 py-2 border border-[#E8D4BA]/50 rounded-lg text-sm focus:ring-2 focus:ring-[#B08968]/30 focus:border-[#B08968] outline-none"
          placeholder="https://example.com/image.jpg"
        />
      </div>
    </div>
  )
}

// Подкомпонент содержимого формы
interface FormContentProps {
  formData: FormData
  formErrors: Record<string, string>
  categories: Category[]
  showAdvanced: boolean
  setShowAdvanced: (v: boolean) => void
  isDragging: boolean
  uploadingCover: boolean
  editingMaterial: Material | null
  onUpdateFormData: (updates: Partial<FormData>) => void
  onSetFormData: (data: FormData) => void
  onClose: () => void
  handleDragOver: (e: React.DragEvent) => void
  handleDragLeave: (e: React.DragEvent) => void
  handleDrop: (e: React.DragEvent) => void
  onProcessImageFile: (file: File) => void
}

function FormContent(props: FormContentProps) {
  const { 
    formData, formErrors, categories,
    showAdvanced, setShowAdvanced, isDragging, uploadingCover, editingMaterial,
    onUpdateFormData, onSetFormData, onClose, handleDragOver, handleDragLeave, 
    handleDrop, onProcessImageFile 
  } = props

  return (
    <>
      {/* Название */}
      <div>
        <label className="block text-sm font-medium text-[#5D4E3A] mb-1.5">Название *</label>
        <input
          type="text"
          value={formData.title}
          onChange={e => onUpdateFormData({ title: e.target.value })}
          className={`w-full px-4 py-3 border rounded-xl focus:ring-2 focus:ring-[#B08968]/30 focus:border-[#B08968] outline-none ${
            formErrors.title ? 'border-red-400 bg-red-50' : 'border-[#E8D4BA]/50'
          }`}
          placeholder="Введите название материала"
        />
        {formErrors.title && <p className="text-red-500 text-xs mt-1">{formErrors.title}</p>}
      </div>

      {/* Описание */}
      <div>
        <label className="block text-sm font-medium text-[#5D4E3A] mb-1.5">Краткое описание</label>
        <textarea
          value={formData.description}
          onChange={e => onUpdateFormData({ description: e.target.value })}
          className="w-full px-4 py-3 border border-[#E8D4BA]/50 rounded-xl focus:ring-2 focus:ring-[#B08968]/30 focus:border-[#B08968] outline-none resize-none"
          rows={2}
          placeholder="Краткое описание для карточки"
        />
      </div>

      {/* Категории */}
      <div>
        <label className="block text-sm font-medium text-[#5D4E3A] mb-2">
          Категории * <span className="text-xs text-[#8B8279] font-normal">(можно выбрать несколько)</span>
        </label>
        <div className="flex flex-wrap gap-2">
          {categories.map(cat => {
            const isSelected = formData.category_ids.includes(cat.id)
            return (
              <button
                key={cat.id}
                type="button"
                onClick={() => {
                  const newIds = isSelected
                    ? formData.category_ids.filter(id => id !== cat.id)
                    : [...formData.category_ids, cat.id]
                  onUpdateFormData({ category_ids: newIds })
                }}
                className={`px-3 py-2 rounded-xl text-sm font-medium transition-all ${
                  isSelected
                    ? 'bg-gradient-to-r from-[#C9A882] to-[#B08968] text-white shadow-md'
                    : 'bg-[#F5E6D3]/50 text-[#5D4E3A] hover:bg-[#F5E6D3] border border-[#E8D4BA]/50'
                }`}
              >
                {cat.icon} {cat.name}
              </button>
            )
          })}
        </div>
        {formData.category_ids.length === 0 && (
          <p className="text-orange-500 text-xs mt-2">Выберите хотя бы одну категорию</p>
        )}
      </div>

      {/* Ссылка */}
      <div className={`p-4 rounded-xl border ${
        formErrors.external_url ? 'bg-red-50 border-red-200' : 'bg-gradient-to-r from-blue-50 to-purple-50 border-blue-100'
      }`}>
        <label className="block text-sm font-medium text-[#5D4E3A] mb-1.5">🔗 Ссылка на материал *</label>
        <input
          type="url"
          value={formData.external_url}
          onChange={e => onUpdateFormData({ external_url: e.target.value })}
          className={`w-full px-4 py-3 border rounded-xl focus:ring-2 focus:ring-[#B08968]/30 focus:border-[#B08968] outline-none bg-white ${
            formErrors.external_url ? 'border-red-400' : 'border-[#E8D4BA]/50'
          }`}
          placeholder="https://notion.so/... или https://t.me/..."
        />
        {formErrors.external_url ? (
          <p className="text-red-500 text-xs mt-2">{formErrors.external_url}</p>
        ) : formData.external_url && (
          <div className="mt-2 flex items-center gap-4 text-xs">
            <span className={`flex items-center gap-1.5 ${getLinkType(formData.external_url).color}`}>
              <span>{getLinkType(formData.external_url).icon}</span>
              <span className="font-medium">{getLinkType(formData.external_url).label}</span>
            </span>
          </div>
        )}
      </div>

      {/* Расширенные настройки */}
      <button
        type="button"
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="flex items-center gap-2 text-sm text-[#8B8279] hover:text-[#5D4E3A] transition-colors"
      >
        <span className={`transform transition-transform ${showAdvanced ? 'rotate-90' : ''}`}>▶</span>
        Расширенные настройки (редактор контента)
      </button>

      {showAdvanced && (
        <div className="p-4 bg-[#F5E6D3]/30 rounded-xl space-y-4">
          <p className="text-xs text-[#8B8279]">Используйте редактор только если материал не является внешней ссылкой</p>
          <RichTextEditor
            content={formData.content}
            onChange={(html) => onSetFormData({...formData, content: html})}
            placeholder="Содержимое материала (опционально)..."
          />
        </div>
      )}

      {/* Обложка */}
      <CoverUpload 
        formData={formData}
        formErrors={formErrors}
        isDragging={isDragging}
        uploadingCover={uploadingCover}
        onUpdateFormData={onUpdateFormData}
        handleDragOver={handleDragOver}
        handleDragLeave={handleDragLeave}
        handleDrop={handleDrop}
        onProcessImageFile={onProcessImageFile}
      />

      {/* Переключатели */}
      <div className="flex flex-wrap gap-4">
        <label className="flex items-center gap-2 cursor-pointer p-3 bg-[#F5E6D3]/30 rounded-xl hover:bg-[#F5E6D3]/50 transition-colors">
          <input
            type="checkbox"
            checked={formData.is_published}
            onChange={e => onUpdateFormData({ is_published: e.target.checked })}
            className="w-5 h-5 rounded border-[#E8D4BA] text-[#B08968] focus:ring-[#B08968]/30"
          />
          <div>
            <span className="text-sm font-medium text-[#5D4E3A]">Опубликовать сразу</span>
            <p className="text-xs text-[#8B8279]">Материал будет виден пользователям</p>
          </div>
        </label>
        <label className="flex items-center gap-2 cursor-pointer p-3 bg-amber-50 rounded-xl hover:bg-amber-100 transition-colors">
          <input
            type="checkbox"
            checked={formData.is_featured}
            onChange={e => onUpdateFormData({ is_featured: e.target.checked })}
            className="w-5 h-5 rounded border-amber-300 text-amber-500 focus:ring-amber-300/30"
          />
          <div>
            <span className="text-sm font-medium text-[#5D4E3A]">⭐ Выбор Полины</span>
            <p className="text-xs text-[#8B8279]">Покажется на главной</p>
          </div>
        </label>
      </div>

      {/* Кнопки */}
      <div className="flex gap-3 pt-4">
        <button
          type="button"
          onClick={onClose}
          className="flex-1 px-5 py-3 border border-[#E8D4BA] text-[#8B8279] rounded-xl font-medium hover:bg-[#F5E6D3]/50 transition-all"
        >
          Отмена
        </button>
        <button
          type="submit"
          className="flex-1 px-5 py-3 bg-gradient-to-r from-[#C9A882] to-[#B08968] text-white rounded-xl font-medium hover:shadow-lg transition-all"
        >
          {editingMaterial ? 'Сохранить изменения' : 'Создать материал'}
        </button>
      </div>
    </>
  )
}

// Подкомпонент предпросмотра для десктопа
function DesktopPreview({ formData, categories, formErrors }: { 
  formData: FormData
  categories: Category[]
  formErrors: Record<string, string>
}) {
  return (
    <div className="w-80 bg-gradient-to-b from-[#F9F6F2] to-[#F5E6D3]/30 border-l border-[#E8D4BA]/30 p-6 hidden lg:block">
      <div className="sticky top-6">
        <h3 className="text-sm font-medium text-[#5D4E3A] mb-4">👁 Предпросмотр</h3>
        
        <div className="bg-white rounded-2xl overflow-hidden shadow-lg border border-[#E8D4BA]/30">
          <div className="aspect-video bg-gradient-to-br from-[#F5E6D3] to-[#E8D4BA] relative overflow-hidden">
            {formData.cover_image ? (
              <img src={formData.cover_image} alt="Превью" className="w-full h-full object-cover"/>
            ) : (
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-4xl opacity-30">📷</span>
              </div>
            )}
            {formData.is_featured && (
              <div className="absolute top-2 right-2 px-2 py-1 bg-amber-400 rounded-lg text-xs font-medium text-white">
                ⭐ Выбор Полины
              </div>
            )}
          </div>
          
          <div className="p-4">
            <h4 className="font-semibold text-[#5D4E3A] mb-1 line-clamp-2">
              {formData.title || 'Название материала'}
            </h4>
            <p className="text-sm text-[#8B8279] mb-3 line-clamp-2">
              {formData.description || 'Описание материала будет здесь...'}
            </p>
            {formData.external_url && (
              <div className={`flex items-center gap-1.5 text-xs ${getLinkType(formData.external_url).color}`}>
                <span>{getLinkType(formData.external_url).icon}</span>
                <span>{getLinkType(formData.external_url).label}</span>
              </div>
            )}
          </div>
        </div>
      
        <div className="mt-4 p-3 bg-white/50 rounded-xl">
          <div className="text-xs text-[#8B8279] space-y-1">
            <p>
              <span className={formData.is_published ? 'text-green-600' : 'text-orange-500'}>●</span>
              {' '}{formData.is_published ? 'Будет опубликован' : 'Черновик'}
            </p>
            <p>📁 {formData.category_ids.length > 0 
              ? categories.filter(c => formData.category_ids.includes(c.id)).map(c => c.name).join(' • ')
              : 'Категория не выбрана'}</p>
          </div>
        </div>

        {Object.keys(formErrors).length > 0 && (
          <div className="mt-4 p-3 bg-red-50 rounded-xl border border-red-200">
            <p className="text-xs font-medium text-red-600 mb-1">⚠️ Заполните поля:</p>
            <ul className="text-xs text-red-500 space-y-0.5">
              {Object.values(formErrors).map((err, i) => (
                <li key={i}>• {err}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

interface MaterialFormModalProps {
  isOpen: boolean
  editingMaterial: Material | null
  categories: Category[]
  formData: FormData
  formErrors: Record<string, string>
  hasUnsavedChanges: boolean
  uploadingCover: boolean
  onClose: () => void
  onSubmit: (e: React.FormEvent) => void
  onUpdateFormData: (updates: Partial<FormData>) => void
  onSetFormData: (data: FormData) => void
  onProcessImageFile: (file: File) => void
}

export function MaterialFormModal({
  isOpen,
  editingMaterial,
  categories,
  formData,
  formErrors,
  hasUnsavedChanges,
  uploadingCover,
  onClose,
  onSubmit,
  onUpdateFormData,
  onSetFormData,
  onProcessImageFile,
}: MaterialFormModalProps) {
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [isDragging, setIsDragging] = useState(false)

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files[0]
    if (file && file.type.startsWith('image/')) {
      onProcessImageFile(file)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-end sm:items-center justify-center pt-12 sm:pt-0 sm:p-4">
      <div className="bg-white rounded-t-3xl sm:rounded-3xl w-full sm:max-w-4xl max-h-[90vh] overflow-hidden flex flex-col sm:flex-row">
        {/* Левая часть - Форма */}
        <div className="flex-1 overflow-y-auto">
          {/* Индикатор для мобильных */}
          <div className="sm:hidden flex justify-center pt-2 pb-1">
            <div className="w-10 h-1 bg-[#E8D4BA] rounded-full"></div>
          </div>
          
          <div className="sticky top-0 bg-white border-b border-[#E8D4BA]/30 px-4 sm:px-6 py-3 sm:py-4 flex justify-between items-center z-10">
            <div>
              <h2 className="text-lg sm:text-xl font-bold text-[#5D4E3A]">
                {editingMaterial ? 'Редактировать' : 'Новый материал'}
              </h2>
              {hasUnsavedChanges && (
                <span className="text-xs text-orange-500">● Несохранённые изменения</span>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="w-8 h-8 rounded-full hover:bg-[#F5E6D3] flex items-center justify-center text-[#8B8279]"
            >
              ✕
            </button>
          </div>
        
          <form onSubmit={onSubmit} className="p-4 sm:p-6 space-y-4 sm:space-y-5">
            {/* Форма будет добавлена далее */}
            <FormContent 
              formData={formData}
              formErrors={formErrors}
              categories={categories}
              showAdvanced={showAdvanced}
              setShowAdvanced={setShowAdvanced}
              isDragging={isDragging}
              uploadingCover={uploadingCover}
              editingMaterial={editingMaterial}
              onUpdateFormData={onUpdateFormData}
              onSetFormData={onSetFormData}
              onClose={onClose}
              handleDragOver={handleDragOver}
              handleDragLeave={handleDragLeave}
              handleDrop={handleDrop}
              onProcessImageFile={onProcessImageFile}
            />
          </form>
        </div>
        
        {/* Правая часть - Предпросмотр */}
        <DesktopPreview formData={formData} categories={categories} formErrors={formErrors} />
      </div>
    </div>
  )
}
