'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import dynamic from 'next/dynamic'
import axios from 'axios'
import { usePresence, Activity as WsActivity, AdminAction as WsAdminAction } from '@/hooks/usePresence'
import { ADMIN_IDS, ADMIN_GROUP_INFO } from '@/lib/constants'
import { getLinkType } from '@/lib/utils'
import { CategoriesTab, HistoryTab, UsersTab } from '@/components/admin'

// API клиент
const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'https://api.librarymomsclub.ru/api',
})

api.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

// Динамический импорт редактора (без SSR)
const RichTextEditor = dynamic(() => import('@/components/RichTextEditor'), { 
  ssr: false,
  loading: () => (
    <div className="border border-[#E8D4BA]/50 rounded-xl p-4 animate-pulse bg-[#F5E6D3]/20">
      <div className="h-4 bg-[#E8D4BA]/30 rounded w-1/4 mb-2"></div>
      <div className="h-4 bg-[#E8D4BA]/30 rounded w-3/4"></div>
    </div>
  )
})

// Типы
interface Category {
  id: number
  name: string
  slug: string
  icon: string
  description?: string
}

interface Material {
  id: number
  title: string
  description?: string
  external_url?: string  // Ссылка на Notion или Telegram
  content?: string
  category_id?: number  // Deprecated
  category_ids: number[]  // Новое: массив ID категорий
  categories?: Category[]  // Новое: массив категорий
  format: string
  cover_image?: string
  is_published: boolean
  is_featured: boolean
  created_at: string
  views: number
}

interface Stats {
  materials: { total: number; published: number; drafts: number }
  views_total: number
  favorites_total: number
  categories_total: number
}

interface Activity {
  type: 'view' | 'favorite' | 'favorite_add' | 'favorite_remove'
  created_at: string
  user: {
    telegram_id: number
    first_name: string
    username?: string
    photo_url?: string
  }
  material: {
    id: number
    title: string
    icon: string
  }
}

interface AdminAction {
  id: number
  admin_id: number
  admin_name: string
  action: 'create' | 'edit' | 'delete' | 'publish' | 'unpublish'
  entity_type: 'material' | 'category' | 'tag'
  entity_id?: number
  entity_title?: string
  details?: string
  created_at: string
}

interface AdminUser {
  telegram_id: number
  first_name: string
  username?: string
  admin_group?: string
  photo_url?: string
}

export default function AdminPage() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [adminUser, setAdminUser] = useState<AdminUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'materials' | 'categories' | 'history' | 'stats' | 'users'>('stats')
  
  // Пользователи и Push
  const [pushSubscribers, setPushSubscribers] = useState<number[]>([])
  const [usersStats, setUsersStats] = useState<{
    users: Array<{
      id: number
      telegram_id: number
      first_name: string
      username?: string
      photo_url?: string
      views_count: number
      favorites_count: number
      last_activity?: string
      has_push: boolean
    }>
    total: number
    with_push: number
  } | null>(null)
  const [copiedUsername, setCopiedUsername] = useState<string | null>(null)
  const [isMenuVisible, setIsMenuVisible] = useState(true)
  const [lastScrollY, setLastScrollY] = useState(0)
  
  // Push рассылка
  const [showPushForm, setShowPushForm] = useState(false)
  const [pushForm, setPushForm] = useState({ title: '', body: '', url: '/library', targetUser: '' })
  const [pushSending, setPushSending] = useState(false)
  
  // Аналитика
  const [analytics, setAnalytics] = useState<{
    views_by_day: { day: string; count: number }[]
    top_materials: { id: number; title: string; views: number }[]
    avg_duration_seconds: number
  } | null>(null)
  
  // Модалка пользователя
  const [selectedUser, setSelectedUser] = useState<{
    user: { id: number; telegram_id: number; first_name: string; username?: string; photo_url?: string }
    views: { title: string; viewed_at: string }[]
    favorites: string[]
    subscription_end?: string
    has_push: boolean
  } | null>(null)
  
  const [stats, setStats] = useState<Stats | null>(null)
  const [materials, setMaterials] = useState<Material[]>([])
  const [loadingMaterials, setLoadingMaterials] = useState(false)
  const [categories, setCategories] = useState<Category[]>([])
  const [recentActivity, setRecentActivity] = useState<Activity[]>([])
  const [adminHistory, setAdminHistory] = useState<AdminAction[]>([])
  const [loadingHistory, setLoadingHistory] = useState(false)
  
  // Поиск и пагинация материалов
  const [materialsSearch, setMaterialsSearch] = useState('')
  const [materialsLimit, setMaterialsLimit] = useState(10)
  
  // Фильтрованные материалы
  const filteredMaterials = useMemo(() => {
    return materials.filter(m => 
      m.title.toLowerCase().includes(materialsSearch.toLowerCase()) ||
      m.description?.toLowerCase().includes(materialsSearch.toLowerCase())
    )
  }, [materials, materialsSearch])
  
  const displayedMaterials = useMemo(() => {
    return filteredMaterials.slice(0, materialsLimit)
  }, [filteredMaterials, materialsLimit])
  
  // Callback для новой активности через WebSocket
  const handleNewActivity = useCallback((activity: WsActivity) => {
    setRecentActivity(prev => [activity as Activity, ...prev].slice(0, 20))
  }, [])
  
  // Callback для действий админов через WebSocket
  const handleAdminAction = useCallback((action: WsAdminAction) => {
    setAdminHistory(prev => [action as AdminAction, ...prev].slice(0, 50))
  }, [])
  
  // WebSocket для отслеживания онлайн пользователей
  const { onlineUsers, isConnected, libraryCount, adminCount } = usePresence('admin', handleNewActivity, handleAdminAction)
  
  const [showMaterialForm, setShowMaterialForm] = useState(false)
  const [editingMaterial, setEditingMaterial] = useState<Material | null>(null)
  
  // Категории
  const [showCategoryForm, setShowCategoryForm] = useState(false)
  const [editingCategory, setEditingCategory] = useState<Category | null>(null)
  const [categoryForm, setCategoryForm] = useState({
    name: '',
    slug: '',
    icon: '📁',
    description: ''
  })
  
  // Загрузка файла
  const [uploadingCover, setUploadingCover] = useState(false)
  
  // Форма материала
  const [formData, setFormData] = useState({
    title: '',
    description: '',
    external_url: '', // Ссылка на Notion или Telegram
    content: '', // Опционально, для материалов без внешней ссылки
    category_ids: [] as number[],  // Новое: массив ID категорий
    format: 'guide',
    cover_image: '',
    is_published: false,
    is_featured: false
  })
  
  const [showAdvanced, setShowAdvanced] = useState(false) // Расширенные настройки
  const [formErrors, setFormErrors] = useState<Record<string, string>>({}) // Валидация
  const [isDragging, setIsDragging] = useState(false) // Drag & drop
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false) // Отслеживание изменений
  const [showPreview, setShowPreview] = useState(false) // Предпросмотр карточки (скрыт по умолчанию на мобильных)

  const router = useRouter()

  // Проверка админа через API
  useEffect(() => {
    const checkAdmin = async () => {
      const token = localStorage.getItem('access_token')
      if (!token) {
        router.push('/login')
        return
      }

      try {
        const response = await api.get('/auth/me')
        const telegramId = response.data.telegram_id
        if (ADMIN_IDS.includes(telegramId)) {
          setIsAdmin(true)
          setAdminUser({
            telegram_id: response.data.telegram_id,
            first_name: response.data.first_name,
            username: response.data.username,
            admin_group: response.data.admin_group,
            photo_url: response.data.photo_url
          })
          loadCategories()
        } else {
          router.push('/library')
        }
      } catch {
        router.push('/login')
      } finally {
        setLoading(false)
      }
    }
    checkAdmin()
  }, [router])

  // Блокируем скролл страницы когда открыто модальное окно
  useEffect(() => {
    if (showMaterialForm || showCategoryForm) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => {
      document.body.style.overflow = ''
    }
  }, [showMaterialForm, showCategoryForm])

  useEffect(() => {
    if (isAdmin) {
      if (activeTab === 'stats') {
        loadStats()
        loadPushSubscribers()
        loadAnalytics()
        loadUsersStats() // для отображения подписчиков push
      }
      if (activeTab === 'materials') loadMaterials()
      if (activeTab === 'history') loadAdminHistory()
      if (activeTab === 'users') loadUsersStats()
    }
  }, [isAdmin, activeTab])

  // Скрытие меню при скролле вниз
  useEffect(() => {
    const handleScroll = () => {
      const currentScrollY = window.scrollY
      if (currentScrollY > lastScrollY && currentScrollY > 100) {
        setIsMenuVisible(false)
      } else {
        setIsMenuVisible(true)
      }
      setLastScrollY(currentScrollY)
    }
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [lastScrollY])

  const loadStats = async () => {
    try {
      const response = await api.get('/admin/stats')
      setStats(response.data)
      // Загружаем ленту активности вместе со статистикой
      loadRecentActivity()
    } catch (error) {
      console.error('Error loading stats:', error)
      // Fallback
      setStats({
        materials: { total: 0, published: 0, drafts: 0 },
        views_total: 0,
        favorites_total: 0,
        categories_total: categories.length
      })
    }
  }
  
  const loadRecentActivity = async () => {
    try {
      const response = await api.get('/activity/recent?limit=15')
      setRecentActivity(response.data)
    } catch (error) {
      console.error('Error loading activity:', error)
    }
  }

  const loadMaterials = async () => {
    setLoadingMaterials(true)
    try {
      const response = await api.get('/materials?include_drafts=true')
      setMaterials(response.data.items || [])
    } catch (error) {
      console.error('Error loading materials:', error)
      setMaterials([])
    } finally {
      setLoadingMaterials(false)
    }
  }

  const loadCategories = async () => {
    try {
      const response = await api.get('/categories')
      setCategories(response.data)
    } catch (error) {
      console.error('Error loading categories:', error)
    }
  }

  const loadPushSubscribers = async () => {
    try {
      const response = await api.get('/push/subscribers')
      setPushSubscribers(response.data.subscribers || [])
    } catch (error) {
      console.error('Error loading push subscribers:', error)
    }
  }

  const loadUsersStats = async () => {
    try {
      const response = await api.get('/push/users-stats')
      setUsersStats(response.data)
    } catch (error) {
      console.error('Error loading users stats:', error)
    }
  }

  const copyUsername = (username: string) => {
    navigator.clipboard.writeText(`@${username}`)
    setCopiedUsername(username)
    setTimeout(() => setCopiedUsername(null), 2000)
  }

  const loadAnalytics = async () => {
    try {
      const response = await api.get('/push/analytics')
      setAnalytics(response.data)
    } catch (error) {
      console.error('Error loading analytics:', error)
    }
  }

  const loadUserDetails = async (telegramId: number) => {
    try {
      const response = await api.get(`/push/user-details/${telegramId}`)
      setSelectedUser(response.data)
    } catch (error) {
      console.error('Error loading user details:', error)
    }
  }

  const sendPush = async (toAll: boolean) => {
    if (!pushForm.title || !pushForm.body) return
    setPushSending(true)
    try {
      if (toAll) {
        await api.post('/push/send-broadcast', null, { 
          params: { title: pushForm.title, body: pushForm.body, url: pushForm.url }
        })
        alert('Push отправлен всем!')
      } else {
        const user = usersStats?.users.find(u => u.username === pushForm.targetUser.replace('@', ''))
        if (!user) {
          alert('Пользователь не найден')
          return
        }
        await api.post('/push/send-to-user', null, {
          params: { telegram_id: user.telegram_id, title: pushForm.title, body: pushForm.body, url: pushForm.url }
        })
        alert(`Push отправлен @${pushForm.targetUser}!`)
      }
      setPushForm({ title: '', body: '', url: '/library', targetUser: '' })
      setShowPushForm(false)
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } }
      alert(err.response?.data?.detail || 'Ошибка отправки')
    } finally {
      setPushSending(false)
    }
  }

  const loadAdminHistory = async () => {
    setLoadingHistory(true)
    try {
      const response = await api.get('/activity/admin-history?limit=50')
      setAdminHistory(response.data)
    } catch (error) {
      console.error('Error loading admin history:', error)
    } finally {
      setLoadingHistory(false)
    }
  }

  // Валидация формы
  const validateForm = (): boolean => {
    const errors: Record<string, string> = {}
    
    if (!formData.title.trim()) {
      errors.title = 'Введите название материала'
    }
    if (!formData.external_url.trim()) {
      errors.external_url = 'Вставьте ссылку на материал'
    } else if (!formData.external_url.startsWith('http')) {
      errors.external_url = 'Ссылка должна начинаться с http:// или https://'
    }
    if (!formData.cover_image) {
      errors.cover_image = 'Добавьте обложку материала'
    }
    if (formData.category_ids.length === 0) {
      errors.category_ids = 'Выберите хотя бы одну категорию'
    }
    
    setFormErrors(errors)
    return Object.keys(errors).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    
    if (!validateForm()) {
      return // Не отправляем если есть ошибки
    }
    
    try {
      // Проверяем размер данных
      const dataSize = JSON.stringify(formData).length
      console.log('Sending data, size:', dataSize, 'bytes')
      
      if (dataSize > 10 * 1024 * 1024) {
        alert('❌ Данные слишком большие. Попробуйте использовать URL изображения вместо загрузки файла.')
        return
      }
      
      if (editingMaterial) {
        // Редактирование
        await api.put(`/materials/${editingMaterial.id}`, formData)
        alert('✅ Материал обновлён!')
      } else {
        // Создание
        await api.post('/materials', formData)
        alert('✅ Материал создан!')
      }
      setShowMaterialForm(false)
      setHasUnsavedChanges(false)
      resetForm()
      loadMaterials()
    } catch (error: unknown) {
      console.error('Error saving material:', error)
      const axiosError = error as { response?: { status?: number; data?: { detail?: string } }; message?: string }
      const status = axiosError.response?.status
      const detail = axiosError.response?.data?.detail
      const message = axiosError.message || 'Неизвестная ошибка'
      console.error('Status:', status, 'Detail:', detail, 'Message:', message)
      alert(`❌ Ошибка: ${detail || message}${status ? ` (${status})` : ''}`)
    }
  }

  const handleDeleteMaterial = async (id: number) => {
    if (!confirm('Удалить этот материал?')) return
    
    try {
      await api.delete(`/materials/${id}`)
      alert('✅ Материал удалён')
      loadMaterials()
    } catch (error) {
      console.error('Error deleting material:', error)
      alert('❌ Ошибка удаления')
    }
  }

  const handleTogglePublish = async (material: Material) => {
    try {
      await api.put(`/materials/${material.id}`, {
        is_published: !material.is_published
      })
      loadMaterials()
    } catch (error) {
      console.error('Error toggling publish:', error)
      alert('❌ Ошибка')
    }
  }

  const handleEditMaterial = (material: Material) => {
    setEditingMaterial(material)
    setFormData({
      title: material.title,
      description: material.description || '',
      external_url: material.external_url || '',
      content: material.content || '',
      category_ids: material.category_ids || (material.category_id ? [material.category_id] : []),
      format: material.format,
      cover_image: material.cover_image || '',
      is_published: material.is_published,
      is_featured: material.is_featured
    })
    setShowMaterialForm(true)
  }

  // Закрытие формы с подтверждением
  const handleCloseForm = () => {
    if (hasUnsavedChanges) {
      if (confirm('У вас есть несохранённые изменения. Закрыть без сохранения?')) {
        setShowMaterialForm(false)
        setHasUnsavedChanges(false)
        resetForm()
      }
    } else {
      setShowMaterialForm(false)
      resetForm()
    }
  }

  // Обновление формы с отслеживанием изменений
  const updateFormData = (updates: Partial<typeof formData>) => {
    setFormData(prev => ({ ...prev, ...updates }))
    setHasUnsavedChanges(true)
    // Убираем ошибку при вводе
    Object.keys(updates).forEach(key => {
      if (formErrors[key]) {
        setFormErrors(prev => {
          const newErrors = { ...prev }
          delete newErrors[key]
          return newErrors
        })
      }
    })
  }

  const resetForm = () => {
    setFormData({
      title: '',
      description: '',
      external_url: '',
      content: '',
      category_ids: [],
      format: 'guide',
      cover_image: '',
      is_published: false,
      is_featured: false
    })
    setEditingMaterial(null)
    setShowAdvanced(false)
    setFormErrors({})
    setHasUnsavedChanges(false)
  }

  // Drag & Drop для обложки
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    
    const file = e.dataTransfer.files[0]
    if (file && file.type.startsWith('image/')) {
      processImageFile(file)
    } else {
      alert('Пожалуйста, перетащите изображение')
    }
  }, [])

  const processImageFile = (file: File) => {
    if (file.size > 10 * 1024 * 1024) {
      alert('Изображение слишком большое. Максимум 10 МБ')
      return
    }
    
    setUploadingCover(true)
    
    // Сжимаем изображение через canvas
    const img = new Image()
    const reader = new FileReader()
    
    reader.onload = (event) => {
      img.src = event.target?.result as string
    }
    
    img.onload = () => {
      const canvas = document.createElement('canvas')
      const ctx = canvas.getContext('2d')
      
      // Максимальный размер 800px по большей стороне
      const maxSize = 800
      let { width, height } = img
      
      if (width > height) {
        if (width > maxSize) {
          height = (height * maxSize) / width
          width = maxSize
        }
      } else {
        if (height > maxSize) {
          width = (width * maxSize) / height
          height = maxSize
        }
      }
      
      canvas.width = width
      canvas.height = height
      ctx?.drawImage(img, 0, 0, width, height)
      
      // Сжимаем в JPEG с качеством 0.7
      const compressedBase64 = canvas.toDataURL('image/jpeg', 0.7)
      console.log('Compressed image size:', compressedBase64.length, 'bytes')
      
      updateFormData({ cover_image: compressedBase64 })
      setUploadingCover(false)
    }
    
    img.onerror = () => {
      alert('Ошибка загрузки изображения')
      setUploadingCover(false)
    }
    
    reader.readAsDataURL(file)
  }

  // ==================== КАТЕГОРИИ ====================
  
  const openCategoryForm = (category?: Category) => {
    if (category) {
      setEditingCategory(category)
      setCategoryForm({
        name: category.name,
        slug: category.slug,
        icon: category.icon,
        description: category.description || ''
      })
    } else {
      setEditingCategory(null)
      setCategoryForm({ name: '', slug: '', icon: '📁', description: '' })
    }
    setShowCategoryForm(true)
  }

  const handleCategorySubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    // TODO: Сохранение через API
    console.log('Saving category:', categoryForm, editingCategory?.id)
    
    if (editingCategory) {
      // Обновляем
      setCategories(categories.map(c => 
        c.id === editingCategory.id 
          ? { ...c, ...categoryForm }
          : c
      ))
    } else {
      // Создаём новую
      const newCategory: Category = {
        id: Math.max(...categories.map(c => c.id)) + 1,
        ...categoryForm
      }
      setCategories([...categories, newCategory])
    }
    
    setShowCategoryForm(false)
    alert('Категория сохранена!')
  }

  const handleDeleteCategory = async (id: number) => {
    const category = categories.find(c => c.id === id)
    if (confirm(`Удалить категорию "${category?.name}"?\n\nВнимание: все материалы этой категории станут без категории.`)) {
      // TODO: Удаление через API
      setCategories(categories.filter(c => c.id !== id))
      alert('Категория удалена!')
    }
  }

  // ==================== ЗАГРУЗКА ФАЙЛОВ ====================
  
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    // Проверка типа
    if (!file.type.startsWith('image/')) {
      alert('Пожалуйста, выберите изображение (JPG, PNG, WebP)')
      return
    }

    // Проверка размера (макс 5MB)
    if (file.size > 5 * 1024 * 1024) {
      alert('Файл слишком большой. Максимум 5 МБ')
      return
    }

    setUploadingCover(true)

    try {
      // TODO: Загрузка на сервер через API
      // const formData = new FormData()
      // formData.append('file', file)
      // const response = await fetch('/api/v1/admin/upload', { method: 'POST', body: formData })
      // const data = await response.json()
      // setFormData(prev => ({ ...prev, cover_image: data.url }))

      // Пока делаем превью локально
      const reader = new FileReader()
      reader.onload = (event) => {
        setFormData(prev => ({ ...prev, cover_image: event.target?.result as string }))
      }
      reader.readAsDataURL(file)
      
    } catch {
      alert('Ошибка загрузки файла')
    } finally {
      setUploadingCover(false)
    }
  }

  // Загрузка
  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-[#FDFCFA] via-[#FBF8F3] to-[#F5EFE6] flex items-center justify-center">
        <div className="text-center">
          <img 
            src="/logolibrary.svg" 
            alt="LibriMomsClub" 
            className="h-20 sm:h-24 w-auto mx-auto mb-4 animate-pulse"
          />
          <p className="text-[#8B8279]">Загрузка...</p>
        </div>
      </div>
    )
  }

  // Нет доступа
  if (!isAdmin) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-[#FDFCFA] via-[#FBF8F3] to-[#F5EFE6] flex items-center justify-center p-4">
        <div className="bg-white/80 backdrop-blur-xl rounded-3xl p-8 shadow-xl border border-[#E8D4BA]/30 text-center max-w-md">
          <div className="w-20 h-20 bg-gradient-to-br from-red-400 to-red-500 rounded-2xl flex items-center justify-center mx-auto mb-6">
            <span className="text-4xl">🚫</span>
          </div>
          <h1 className="text-2xl font-bold text-[#5D4E3A] mb-3">Доступ запрещён</h1>
          <p className="text-[#8B8279] mb-6">
            Эта страница доступна только администраторам библиотеки.
          </p>
          <a 
            href="/library"
            className="inline-block px-6 py-3 bg-gradient-to-r from-[#C9A882] to-[#B08968] text-white rounded-xl font-medium hover:shadow-lg transition-all"
          >
            Вернуться в библиотеку
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#FDFCFA] via-[#FBF8F3] to-[#F5EFE6]">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-white/50 shadow-lg" style={{ background: 'rgba(255,255,255,0.55)', backdropFilter: 'blur(20px) saturate(180%)', paddingTop: 'env(safe-area-inset-top)' }}>
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <img 
              src="/logolibrary.svg" 
              alt="LibriMomsClub" 
              className="h-10 w-auto"
            />
            <a 
              href="/library"
              className="px-4 py-2.5 bg-gradient-to-r from-[#C9A882] to-[#B08968] text-white rounded-xl font-medium text-sm hover:shadow-lg hover:-translate-y-0.5 transition-all flex items-center gap-2"
            >
              <span>📚</span> В библиотеку
            </a>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Приветственный блок */}
        {adminUser && (
          <div className="mb-6 bg-white/80 backdrop-blur-xl rounded-2xl p-5 border border-[#E8D4BA]/30">
            <div className="flex items-center gap-4">
              {adminUser.photo_url ? (
                <img 
                  src={adminUser.photo_url} 
                  alt={adminUser.first_name}
                  className="w-14 h-14 rounded-2xl object-cover shadow-lg"
                />
              ) : (
                <div className="w-14 h-14 bg-gradient-to-br from-[#C9A882] to-[#B08968] rounded-2xl flex items-center justify-center text-2xl shadow-lg text-white font-bold">
                  {adminUser.first_name.charAt(0)}
                </div>
              )}
              <div>
                <p className="text-xs text-[#B08968] font-medium uppercase tracking-wide mb-0.5">Панель администратора</p>
                <h2 className="text-xl font-bold text-[#5D4E3A]">
                  Привет, {adminUser.first_name}! 👋
                </h2>
                {adminUser.admin_group && ADMIN_GROUP_INFO[adminUser.admin_group] && (
                  <p className="text-sm text-[#8B8279] flex items-center gap-1.5 mt-0.5">
                    <span>{ADMIN_GROUP_INFO[adminUser.admin_group].emoji}</span>
                    <span>{ADMIN_GROUP_INFO[adminUser.admin_group].name}</span>
                  </p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Виджет онлайн пользователей - только на вкладке статистики */}
        {activeTab === 'stats' && (
        <div className="mb-6 grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* В библиотеке */}
          <div className="bg-white/80 backdrop-blur-xl rounded-2xl p-4 border border-[#E8D4BA]/30">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-medium text-[#5D4E3A] flex items-center gap-2">
                <span className="text-lg">📚</span> В библиотеке
                <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-gray-300'}`}></span>
              </h3>
              <span className="text-sm text-[#8B8279]">{libraryCount} онлайн</span>
            </div>
            {onlineUsers.library.length > 0 ? (
              <div className="space-y-2 max-h-[200px] overflow-y-auto">
                {onlineUsers.library.slice(0, 8).map((user) => (
                  <div 
                    key={user.telegram_id} 
                    className="flex items-center gap-2 bg-[#F5E6D3]/50 rounded-lg px-3 py-2"
                  >
                    {user.photo_url ? (
                      <img src={user.photo_url} alt="" className="w-7 h-7 rounded-full" />
                    ) : (
                      <div className="w-7 h-7 rounded-full bg-[#B08968] text-white text-xs flex items-center justify-center">
                        {user.first_name.charAt(0)}
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <span className="text-sm text-[#5D4E3A] font-medium truncate block">{user.first_name}</span>
                      {user.username && (
                        <button 
                          onClick={() => copyUsername(user.username!)}
                          className="text-xs text-[#8B8279] hover:text-[#B08968] transition-colors"
                        >
                          @{user.username} {copiedUsername === user.username && '✓'}
                        </button>
                      )}
                    </div>
                    <span className="text-sm" title={pushSubscribers.includes(user.telegram_id) ? 'Push вкл' : 'Push выкл'}>
                      {pushSubscribers.includes(user.telegram_id) ? '🔔' : '⚪'}
                    </span>
                  </div>
                ))}
                {onlineUsers.library.length > 8 && (
                  <p className="text-xs text-[#8B8279] text-center">+{onlineUsers.library.length - 8} ещё</p>
                )}
              </div>
            ) : (
              <p className="text-sm text-[#8B8279]">Никого нет онлайн</p>
            )}
          </div>

          {/* В админке */}
          <div className="bg-white/80 backdrop-blur-xl rounded-2xl p-4 border border-[#E8D4BA]/30">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-medium text-[#5D4E3A] flex items-center gap-2">
                <span className="text-lg">⚙️</span> В админке
                <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-gray-300'}`}></span>
              </h3>
              <span className="text-sm text-[#8B8279]">{adminCount} онлайн</span>
            </div>
            {onlineUsers.admin.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {onlineUsers.admin.map((user) => (
                  <div 
                    key={user.telegram_id} 
                    className="flex items-center gap-2 bg-gradient-to-r from-amber-50 to-orange-50 rounded-lg px-2 py-1 border border-amber-200/50"
                    title={`${user.first_name}${user.admin_group ? ` (${ADMIN_GROUP_INFO[user.admin_group]?.name || ''})` : ''}`}
                  >
                    {user.photo_url ? (
                      <img src={user.photo_url} alt="" className="w-6 h-6 rounded-full" />
                    ) : (
                      <div className="w-6 h-6 rounded-full bg-[#B08968] text-white text-xs flex items-center justify-center">
                        {user.first_name.charAt(0)}
                      </div>
                    )}
                    <span className="text-xs text-[#5D4E3A] font-medium">{user.first_name}</span>
                    {user.admin_group && ADMIN_GROUP_INFO[user.admin_group] && (
                      <span className="text-xs">{ADMIN_GROUP_INFO[user.admin_group].emoji}</span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-[#8B8279]">Никого нет онлайн</p>
            )}
          </div>
        </div>
        )}

        {/* Tabs - только на десктопе */}
        <div className="hidden sm:flex gap-2 mb-6 bg-white/60 backdrop-blur-lg rounded-2xl p-2 border border-[#E8D4BA]/20 overflow-x-auto">
          {[
            { id: 'stats', label: '📊', labelFull: 'Статистика' },
            { id: 'materials', label: '📚', labelFull: 'Материалы' },
            { id: 'categories', label: '📁', labelFull: 'Категории' },
            { id: 'history', label: '📝', labelFull: 'История' },
            { id: 'users', label: '👥', labelFull: 'Пользователи' }
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
              className={`flex-1 min-w-0 px-4 py-3 rounded-xl font-medium text-sm transition-all whitespace-nowrap ${
                activeTab === tab.id
                  ? 'bg-gradient-to-r from-[#C9A882] to-[#B08968] text-white shadow-lg'
                  : 'text-[#8B8279] hover:bg-white/50'
              }`}
            >
              {tab.label} {tab.labelFull}
            </button>
          ))}
        </div>
        
        {/* Мобильный заголовок таба */}
        <div className="sm:hidden mb-4 text-center">
          <span className="text-lg font-medium text-[#5D4E3A]">
            {activeTab === 'stats' && '📊 Статистика'}
            {activeTab === 'materials' && '📚 Материалы'}
            {activeTab === 'categories' && '📁 Категории'}
            {activeTab === 'history' && '📝 История'}
            {activeTab === 'users' && '👥 Пользователи'}
          </span>
        </div>

        {/* Stats Tab */}
        {activeTab === 'stats' && stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-white/80 backdrop-blur-xl rounded-2xl p-6 border border-[#E8D4BA]/30">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-gradient-to-br from-blue-400 to-blue-500 rounded-xl flex items-center justify-center">
                  <span className="text-2xl">📚</span>
                </div>
                <div>
                  <p className="text-2xl font-bold text-[#5D4E3A]">{stats.materials.total}</p>
                  <p className="text-sm text-[#8B8279]">Материалов</p>
                </div>
              </div>
              <div className="mt-4 flex gap-4 text-xs">
                <span className="text-green-600">✓ {stats.materials.published} опубл.</span>
                <span className="text-orange-500">◐ {stats.materials.drafts} черновик</span>
              </div>
            </div>

            <div className="bg-white/80 backdrop-blur-xl rounded-2xl p-6 border border-[#E8D4BA]/30">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-gradient-to-br from-purple-400 to-purple-500 rounded-xl flex items-center justify-center">
                  <span className="text-2xl">👁</span>
                </div>
                <div>
                  <p className="text-2xl font-bold text-[#5D4E3A]">{stats.views_total}</p>
                  <p className="text-sm text-[#8B8279]">Просмотров</p>
                </div>
              </div>
            </div>

            <div className="bg-white/80 backdrop-blur-xl rounded-2xl p-6 border border-[#E8D4BA]/30">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-gradient-to-br from-pink-400 to-pink-500 rounded-xl flex items-center justify-center">
                  <span className="text-2xl">⭐</span>
                </div>
                <div>
                  <p className="text-2xl font-bold text-[#5D4E3A]">{stats.favorites_total}</p>
                  <p className="text-sm text-[#8B8279]">В избранном</p>
                </div>
              </div>
            </div>

            <div className="bg-white/80 backdrop-blur-xl rounded-2xl p-6 border border-[#E8D4BA]/30">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-gradient-to-br from-amber-400 to-amber-500 rounded-xl flex items-center justify-center">
                  <span className="text-2xl">📁</span>
                </div>
                <div>
                  <p className="text-2xl font-bold text-[#5D4E3A]">{stats.categories_total}</p>
                  <p className="text-sm text-[#8B8279]">Категорий</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Push-рассылка и Аналитика */}
        {activeTab === 'stats' && (
          <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Кнопка Push */}
            <div className="bg-white/80 backdrop-blur-xl rounded-2xl p-5 border border-[#E8D4BA]/30">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-[#5D4E3A] flex items-center gap-2">
                  <span>🔔</span> Push-рассылка
                </h3>
                <span className="text-sm text-[#8B8279]">{usersStats?.with_push || 0} подписчиков</span>
              </div>
              {!showPushForm ? (
                <button
                  onClick={() => setShowPushForm(true)}
                  className="w-full py-3 bg-gradient-to-r from-[#C9A882] to-[#B08968] text-white rounded-xl font-medium hover:shadow-lg transition-all"
                >
                  Отправить Push
                </button>
              ) : (
                <div className="space-y-3">
                  <input
                    type="text"
                    placeholder="Заголовок"
                    value={pushForm.title}
                    onChange={(e) => setPushForm({...pushForm, title: e.target.value})}
                    className="w-full px-4 py-2 border border-[#E8D4BA]/50 rounded-xl focus:ring-2 focus:ring-[#B08968]/30 outline-none"
                  />
                  <textarea
                    placeholder="Текст сообщения"
                    value={pushForm.body}
                    onChange={(e) => setPushForm({...pushForm, body: e.target.value})}
                    className="w-full px-4 py-2 border border-[#E8D4BA]/50 rounded-xl focus:ring-2 focus:ring-[#B08968]/30 outline-none resize-none"
                    rows={2}
                  />
                  {/* Выбор получателя */}
                  <div className="space-y-2">
                    <p className="text-xs text-[#8B8279]">Кому отправить:</p>
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={() => setPushForm({...pushForm, targetUser: ''})}
                        className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${
                          !pushForm.targetUser ? 'bg-[#B08968] text-white' : 'bg-[#F5E6D3]/50 text-[#8B8279] hover:bg-[#F5E6D3]'
                        }`}
                      >
                        👥 Всем ({usersStats?.with_push || 0})
                      </button>
                    </div>
                    <div className="space-y-1 max-h-[150px] overflow-y-auto">
                      {usersStats?.users.filter(u => u.has_push).map(u => (
                        <button
                          key={u.telegram_id}
                          onClick={() => setPushForm({...pushForm, targetUser: u.username || String(u.telegram_id)})}
                          className={`w-full flex items-center gap-2 p-2 rounded-xl text-left transition-all ${
                            pushForm.targetUser === (u.username || String(u.telegram_id)) 
                              ? 'bg-[#B08968] text-white' 
                              : 'bg-[#F5E6D3]/30 hover:bg-[#F5E6D3]/50'
                          }`}
                        >
                          {u.photo_url ? (
                            <img src={u.photo_url} alt="" className="w-8 h-8 rounded-full" />
                          ) : (
                            <div className="w-8 h-8 rounded-full bg-[#B08968] text-white text-sm flex items-center justify-center">
                              {u.first_name?.charAt(0) || '?'}
                            </div>
                          )}
                          <div className="flex-1 min-w-0">
                            <p className={`text-sm font-medium truncate ${pushForm.targetUser === (u.username || String(u.telegram_id)) ? 'text-white' : 'text-[#5D4E3A]'}`}>
                              {u.first_name || 'Без имени'}
                            </p>
                            {u.username && (
                              <p className={`text-xs truncate ${pushForm.targetUser === (u.username || String(u.telegram_id)) ? 'text-white/80' : 'text-[#8B8279]'}`}>
                                @{u.username}
                              </p>
                            )}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => sendPush(!pushForm.targetUser)}
                      disabled={pushSending || !pushForm.title || !pushForm.body}
                      className="flex-1 py-2 bg-gradient-to-r from-[#C9A882] to-[#B08968] text-white rounded-xl font-medium disabled:opacity-50"
                    >
                      {pushSending ? '⏳' : pushForm.targetUser ? `Отправить ${pushForm.targetUser}` : 'Отправить всем'}
                    </button>
                    <button
                      onClick={() => { setShowPushForm(false); setPushForm({...pushForm, title: '', body: '', targetUser: ''}); }}
                      className="px-4 py-2 border border-[#E8D4BA] text-[#8B8279] rounded-xl"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Топ материалов */}
            <div className="bg-white/80 backdrop-blur-xl rounded-2xl p-5 border border-[#E8D4BA]/30">
              <h3 className="font-semibold text-[#5D4E3A] mb-4 flex items-center gap-2">
                <span>🏆</span> Топ за неделю
              </h3>
              {analytics?.top_materials.length ? (
                <div className="space-y-2">
                  {analytics.top_materials.map((m, i) => (
                    <div key={m.id} className="flex items-center gap-3 p-2 rounded-lg hover:bg-[#F5E6D3]/30">
                      <span className="text-lg">{i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `${i+1}.`}</span>
                      <span className="flex-1 text-sm text-[#5D4E3A] truncate">{m.title}</span>
                      <span className="text-sm text-[#8B8279]">{m.views} 👁</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-[#8B8279]">Нет данных</p>
              )}
            </div>
          </div>
        )}

        {/* Лента активности - только на вкладке статистики */}
        {activeTab === 'stats' && recentActivity.length > 0 && (
          <div className="mt-6 bg-white/80 backdrop-blur-xl rounded-2xl p-5 border border-[#E8D4BA]/30">
            <h3 className="font-semibold text-[#5D4E3A] mb-4 flex items-center gap-2">
              <span>📋</span> Последние действия
            </h3>
            <div className="space-y-3 max-h-[400px] overflow-y-auto">
              {recentActivity.map((activity, index) => (
                <div 
                  key={index}
                  className="flex items-center gap-3 p-3 bg-[#F5E6D3]/30 rounded-xl hover:bg-[#F5E6D3]/50 transition-colors"
                >
                  {/* Аватар */}
                  {activity.user.photo_url ? (
                    <img src={activity.user.photo_url} alt="" className="w-9 h-9 rounded-full" />
                  ) : (
                    <div className="w-9 h-9 rounded-full bg-[#B08968] text-white text-sm flex items-center justify-center font-medium">
                      {activity.user.first_name.charAt(0)}
                    </div>
                  )}
                  
                  {/* Контент */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-[#5D4E3A]">
                      <span className="font-medium">{activity.user.first_name}</span>
                      <span className="text-[#8B8279]">
                        {activity.type === 'view' && ' открыл(а) '}
                        {activity.type === 'favorite_add' && ' добавил(а) в избранное '}
                        {activity.type === 'favorite_remove' && ' убрал(а) из избранного '}
                        {activity.type === 'favorite' && ' добавил(а) в избранное '}
                      </span>
                      <span className="font-medium truncate">{activity.material.icon} {activity.material.title}</span>
                    </p>
                    <p className="text-xs text-[#8B8279] mt-0.5">
                      {new Date(activity.created_at).toLocaleString('ru-RU', { 
                        day: 'numeric', 
                        month: 'short', 
                        hour: '2-digit', 
                        minute: '2-digit' 
                      })}
                    </p>
                  </div>
                  
                  {/* Иконка действия */}
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                    activity.type === 'view' 
                      ? 'bg-blue-100 text-blue-600' 
                      : activity.type === 'favorite_remove'
                        ? 'bg-gray-100 text-gray-600'
                        : 'bg-pink-100 text-pink-600'
                  }`}>
                    {activity.type === 'view' && '👁'}
                    {activity.type === 'favorite_add' && '⭐'}
                    {activity.type === 'favorite_remove' && '💔'}
                    {activity.type === 'favorite' && '⭐'}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Materials Tab */}
        {activeTab === 'materials' && (
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
                      setMaterialsLimit(10) // Сброс пагинации при поиске
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
                  onClick={() => {
                    resetForm()
                    setShowMaterialForm(true)
                  }}
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
                  <span className="text-3xl">{materialsSearch ? '�' : '�'}</span>
                </div>
                <h3 className="text-lg font-medium text-[#5D4E3A] mb-2">
                  {materialsSearch ? 'Ничего не найдено' : 'Пока нет материалов'}
                </h3>
                <p className="text-[#8B8279] mb-4">
                  {materialsSearch ? `По запросу "${materialsSearch}" ничего не найдено` : 'Добавьте первый материал в библиотеку'}
                </p>
                {!materialsSearch && (
                  <button
                    onClick={() => setShowMaterialForm(true)}
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
                          <p className="text-xs text-[#8B8279]">
                            {material.category_ids?.length > 0 
                              ? categories.filter(c => material.category_ids.includes(c.id)).map(c => c.name).join(' • ')
                              : (material.category_id ? categories.find(c => c.id === material.category_id)?.name : '-')}
                          </p>
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
                            onClick={() => handleTogglePublish(material)}
                            className={`px-3 py-1.5 text-xs rounded-lg ${
                              material.is_published 
                                ? 'text-orange-600 bg-orange-50' 
                                : 'text-green-600 bg-green-50'
                            }`}
                          >
                            {material.is_published ? 'Снять' : 'Опубл.'}
                          </button>
                          <button
                            onClick={() => handleEditMaterial(material)}
                            className="px-3 py-1.5 text-xs text-[#B08968] bg-[#F5E6D3]/50 rounded-lg"
                          >
                            ✏️
                          </button>
                          <button
                            onClick={() => handleDeleteMaterial(material.id)}
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
                          <td className="px-4 py-3 text-sm text-[#8B8279]">
                            {material.category_ids?.length > 0 
                              ? categories.filter(c => material.category_ids.includes(c.id)).map(c => c.name).join(' • ')
                              : (material.category_id ? categories.find(c => c.id === material.category_id)?.name : '-')}
                          </td>
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
                              onClick={() => handleTogglePublish(material)}
                              className={`px-3 py-1 text-sm rounded-lg ${
                                material.is_published 
                                  ? 'text-orange-500 hover:bg-orange-50' 
                                  : 'text-green-600 hover:bg-green-50'
                              }`}
                            >
                              {material.is_published ? '📤 Снять' : '✅ Опубликовать'}
                            </button>
                            <button
                              onClick={() => handleEditMaterial(material)}
                              className="px-3 py-1 text-sm text-[#B08968] hover:bg-[#F5E6D3] rounded-lg"
                            >
                              ✏️ Редактировать
                            </button>
                            <button
                              onClick={() => handleDeleteMaterial(material.id)}
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
        )}

        {/* Categories Tab */}
        {activeTab === 'categories' && (
          <CategoriesTab 
            categories={categories}
            onOpenForm={openCategoryForm}
            onDelete={handleDeleteCategory}
          />
        )}

        {/* История действий админов */}
        {activeTab === 'history' && (
          <HistoryTab 
            adminHistory={adminHistory}
            loadingHistory={loadingHistory}
          />
        )}
      </div>

      {/* Material Form Modal */}
      {showMaterialForm && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-end sm:items-center justify-center pt-12 sm:pt-0 sm:p-4">
          <div className="bg-white rounded-t-3xl sm:rounded-3xl w-full sm:max-w-4xl max-h-[90vh] sm:max-h-[90vh] overflow-hidden flex flex-col sm:flex-row">
            
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
                  onClick={handleCloseForm}
                  className="w-8 h-8 rounded-full hover:bg-[#F5E6D3] flex items-center justify-center text-[#8B8279]"
                >
                  ✕
                </button>
              </div>
            
              <form onSubmit={handleSubmit} className="p-4 sm:p-6 space-y-4 sm:space-y-5">
                {/* Мобильный предпросмотр */}
                <div className="lg:hidden">
                  <button
                    type="button"
                    onClick={() => setShowPreview(!showPreview)}
                    className="w-full flex items-center justify-between p-3 bg-[#F5E6D3]/50 rounded-xl"
                  >
                    <span className="text-sm font-medium text-[#5D4E3A]">
                      👁 {showPreview ? 'Скрыть' : 'Показать'} предпросмотр
                    </span>
                    <span className={`transform transition-transform ${showPreview ? 'rotate-180' : ''}`}>▼</span>
                  </button>
                  
                  {showPreview && (
                    <div className="mt-3 bg-white rounded-2xl overflow-hidden shadow-lg border border-[#E8D4BA]/30">
                      {/* Обложка */}
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
                        <p className="text-sm text-[#8B8279] mb-2 line-clamp-2">
                          {formData.description || 'Описание материала...'}
                        </p>
                        {formData.external_url && (
                          <div className={`flex items-center gap-1.5 text-xs ${getLinkType(formData.external_url).color}`}>
                            <span>{getLinkType(formData.external_url).icon}</span>
                            <span>{getLinkType(formData.external_url).label}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* Название */}
                <div>
                  <label className="block text-sm font-medium text-[#5D4E3A] mb-1.5">
                    Название *
                  </label>
                  <input
                    type="text"
                    value={formData.title}
                    onChange={e => updateFormData({ title: e.target.value })}
                    className={`w-full px-4 py-3 border rounded-xl focus:ring-2 focus:ring-[#B08968]/30 focus:border-[#B08968] outline-none ${
                      formErrors.title ? 'border-red-400 bg-red-50' : 'border-[#E8D4BA]/50'
                    }`}
                    placeholder="Введите название материала"
                  />
                  {formErrors.title && (
                    <p className="text-red-500 text-xs mt-1">{formErrors.title}</p>
                  )}
                </div>

                {/* Описание */}
                <div>
                  <label className="block text-sm font-medium text-[#5D4E3A] mb-1.5">
                    Краткое описание
                  </label>
                  <textarea
                    value={formData.description}
                    onChange={e => updateFormData({ description: e.target.value })}
                    className="w-full px-4 py-3 border border-[#E8D4BA]/50 rounded-xl focus:ring-2 focus:ring-[#B08968]/30 focus:border-[#B08968] outline-none resize-none"
                    rows={2}
                    placeholder="Краткое описание для карточки"
                  />
                </div>

                {/* Категории (мульти-выбор) */}
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
                            updateFormData({ category_ids: newIds })
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

              {/* 🔗 ССЫЛКА НА МАТЕРИАЛ - ГЛАВНОЕ ПОЛЕ */}
              <div className={`p-4 rounded-xl border ${
                formErrors.external_url 
                  ? 'bg-red-50 border-red-200' 
                  : 'bg-gradient-to-r from-blue-50 to-purple-50 border-blue-100'
              }`}>
                <label className="block text-sm font-medium text-[#5D4E3A] mb-1.5">
                  🔗 Ссылка на материал *
                </label>
                <input
                  type="url"
                  value={formData.external_url}
                  onChange={e => updateFormData({ external_url: e.target.value })}
                  className={`w-full px-4 py-3 border rounded-xl focus:ring-2 focus:ring-[#B08968]/30 focus:border-[#B08968] outline-none bg-white ${
                    formErrors.external_url ? 'border-red-400' : 'border-[#E8D4BA]/50'
                  }`}
                  placeholder="https://notion.so/... или https://t.me/..."
                />
                {formErrors.external_url ? (
                  <p className="text-red-500 text-xs mt-2">{formErrors.external_url}</p>
                ) : (
                  <div className="mt-2 flex items-center gap-4 text-xs">
                    {formData.external_url ? (
                      <span className={`flex items-center gap-1.5 ${getLinkType(formData.external_url).color}`}>
                        <span>{getLinkType(formData.external_url).icon}</span>
                        <span className="font-medium">{getLinkType(formData.external_url).label}</span>
                        <span className="text-[#8B8279]">— {formData.external_url.slice(0, 40)}...</span>
                      </span>
                    ) : (
                      <span className="text-[#8B8279]">Вставьте ссылку на Notion, Telegram или YouTube</span>
                    )}
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
                  <p className="text-xs text-[#8B8279]">
                    Используйте редактор только если материал не является внешней ссылкой
                  </p>
                  <RichTextEditor
                    content={formData.content}
                    onChange={(html) => setFormData({...formData, content: html})}
                    placeholder="Содержимое материала (опционально)..."
                  />
                </div>
              )}

              {/* Обложка с Drag & Drop */}
              <div>
                <label className="block text-sm font-medium text-[#5D4E3A] mb-1.5">
                  Обложка *
                </label>
                
                {/* Превью обложки */}
                {formData.cover_image && (
                  <div className="relative mb-3 rounded-xl overflow-hidden bg-[#F5E6D3]">
                    <img 
                      src={formData.cover_image} 
                      alt="Превью обложки"
                      className="w-full h-48 object-cover"
                    />
                    <button
                      type="button"
                      onClick={() => updateFormData({ cover_image: '' })}
                      className="absolute top-2 right-2 w-8 h-8 bg-black/50 hover:bg-black/70 text-white rounded-full flex items-center justify-center transition-colors"
                    >
                      ✕
                    </button>
                  </div>
                )}

                {/* Drag & Drop зона */}
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
                      if (file) processImageFile(file)
                    }}
                    className="hidden"
                    id="cover-upload"
                    disabled={uploadingCover}
                  />
                  <label 
                    htmlFor="cover-upload"
                    className="cursor-pointer block"
                  >
                    {uploadingCover ? (
                      <div className="flex items-center justify-center gap-2 text-[#8B8279]">
                        <div className="w-5 h-5 border-2 border-[#B08968] border-t-transparent rounded-full animate-spin"></div>
                        Загрузка...
                      </div>
                    ) : isDragging ? (
                      <>
                        <div className="w-16 h-16 bg-[#B08968] rounded-2xl flex items-center justify-center mx-auto mb-3">
                          <span className="text-3xl">�</span>
                        </div>
                        <p className="text-base font-medium text-[#B08968]">
                          Отпустите для загрузки
                        </p>
                      </>
                    ) : (
                      <>
                        <div className="w-14 h-14 bg-[#F5E6D3] rounded-2xl flex items-center justify-center mx-auto mb-3">
                          <span className="text-2xl">📷</span>
                        </div>
                        <p className="text-sm font-medium text-[#5D4E3A]">
                          Перетащите изображение сюда
                        </p>
                        <p className="text-xs text-[#8B8279] mt-1">
                          или нажмите для выбора • JPG, PNG, WebP • до 5 МБ
                        </p>
                        <p className="text-xs text-[#B08968] mt-2 font-medium">
                          Рекомендуемый размер: 1200 × 675 px (16:9)
                        </p>
                      </>
                    )}
                  </label>
                </div>
                
                {formErrors.cover_image && (
                  <p className="text-red-500 text-xs mt-2">{formErrors.cover_image}</p>
                )}

                {/* Или URL */}
                <div className="mt-3">
                  <label className="block text-xs text-[#8B8279] mb-1">Или вставьте URL изображения:</label>
                  <input
                    type="url"
                    value={formData.cover_image.startsWith('data:') ? '' : formData.cover_image}
                    onChange={e => updateFormData({ cover_image: e.target.value })}
                    className="w-full px-3 py-2 border border-[#E8D4BA]/50 rounded-lg text-sm focus:ring-2 focus:ring-[#B08968]/30 focus:border-[#B08968] outline-none"
                    placeholder="https://example.com/image.jpg"
                  />
                </div>
              </div>

              {/* Переключатели */}
              <div className="flex flex-wrap gap-4">
                <label className="flex items-center gap-2 cursor-pointer p-3 bg-[#F5E6D3]/30 rounded-xl hover:bg-[#F5E6D3]/50 transition-colors">
                  <input
                    type="checkbox"
                    checked={formData.is_published}
                    onChange={e => updateFormData({ is_published: e.target.checked })}
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
                    onChange={e => updateFormData({ is_featured: e.target.checked })}
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
                  onClick={handleCloseForm}
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
            </form>
            </div>
            
            {/* Правая часть - Предпросмотр карточки */}
            <div className="w-80 bg-gradient-to-b from-[#F9F6F2] to-[#F5E6D3]/30 border-l border-[#E8D4BA]/30 p-6 hidden lg:block">
              <div className="sticky top-6">
                <h3 className="text-sm font-medium text-[#5D4E3A] mb-4">👁 Предпросмотр</h3>
                
                <div className="bg-white rounded-2xl overflow-hidden shadow-lg border border-[#E8D4BA]/30">
                    {/* Обложка */}
                    <div className="aspect-video bg-gradient-to-br from-[#F5E6D3] to-[#E8D4BA] relative overflow-hidden">
                      {formData.cover_image ? (
                        <img 
                          src={formData.cover_image} 
                          alt="Превью"
                          className="w-full h-full object-cover"
                        />
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
                    
                    {/* Контент */}
                    <div className="p-4">
                      <h4 className="font-semibold text-[#5D4E3A] mb-1 line-clamp-2">
                        {formData.title || 'Название материала'}
                      </h4>
                      <p className="text-sm text-[#8B8279] mb-3 line-clamp-2">
                        {formData.description || 'Описание материала будет здесь...'}
                      </p>
                      
                      {/* Тип ссылки */}
                      {formData.external_url && (
                        <div className={`flex items-center gap-1.5 text-xs ${getLinkType(formData.external_url).color}`}>
                          <span>{getLinkType(formData.external_url).icon}</span>
                          <span>{getLinkType(formData.external_url).label}</span>
                        </div>
                      )}
                    </div>
                  </div>
                
                {/* Статус */}
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

                {/* Ошибки валидации */}
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
          </div>
        </div>
      )}

      {/* Category Form Modal */}
      {showCategoryForm && (
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
            
            <form id="category-form" onSubmit={handleCategorySubmit} className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4">
              {/* Иконка */}
              <div>
                <label className="block text-sm font-medium text-[#5D4E3A] mb-1.5">
                  Иконка (эмодзи)
                </label>
                
                {/* Быстрый выбор */}
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {['📚', '🎬', '💡', '📱', '✨', '🏆', '🎙️', '🤝', '📝', '🎨', '💼', '🌟', '🎯', '💎', '🔥', '💕'].map(emoji => (
                    <button
                      key={emoji}
                      type="button"
                      onClick={() => setCategoryForm({...categoryForm, icon: emoji})}
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
                      onChange={e => setCategoryForm({...categoryForm, icon: e.target.value})}
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
                  onChange={e => {
                    const name = e.target.value
                    const slug = name.toLowerCase()
                      .replace(/[^\w\sа-яё-]/gi, '')
                      .replace(/\s+/g, '-')
                      .replace(/[а-яё]/g, c => {
                        const map: Record<string, string> = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'}
                        return map[c] || c
                      })
                    setCategoryForm({...categoryForm, name, slug})
                  }}
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
                    onChange={e => setCategoryForm({...categoryForm, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '')})}
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
                  onChange={e => setCategoryForm({...categoryForm, description: e.target.value})}
                  className="w-full px-4 py-3 border border-[#E8D4BA]/50 rounded-xl focus:ring-2 focus:ring-[#B08968]/30 focus:border-[#B08968] outline-none resize-none"
                  rows={2}
                  placeholder="Краткое описание категории..."
                />
              </div>

            </form>
            
            {/* Кнопки - фиксированы внизу */}
            <div className="flex gap-3 p-4 sm:p-6 border-t border-[#E8D4BA]/30 bg-white shrink-0" style={{ paddingBottom: 'max(16px, calc(env(safe-area-inset-bottom) + 60px))' }}>
              <button
                type="button"
                onClick={() => setShowCategoryForm(false)}
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
      )}
      
      {/* Users Tab */}
      {activeTab === 'users' && (
        <UsersTab
          usersStats={usersStats}
          onLoadUserDetails={loadUserDetails}
          onCopyUsername={copyUsername}
          copiedUsername={copiedUsername}
        />
      )}
      
      {/* Нижнее меню - только на мобилке */}
      <nav 
        className={`sm:hidden fixed bottom-0 left-0 right-0 bg-white/70 backdrop-blur-2xl border-t border-[#E8D4BA]/20 px-2 py-2 z-50 transition-transform duration-300 ${
          isMenuVisible ? 'translate-y-0' : 'translate-y-full'
        }`} 
        style={{ paddingBottom: 'max(8px, env(safe-area-inset-bottom))' }}
      >
        <div className="flex justify-around items-center">
          {[
            { id: 'stats', icon: '📊', label: 'Статистика' },
            { id: 'materials', icon: '📚', label: 'Материалы' },
            { id: 'categories', icon: '📁', label: 'Категории' },
            { id: 'history', icon: '📝', label: 'История' },
            { id: 'users', icon: '👥', label: 'Польз-ли' }
          ].map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
              className={`flex flex-col items-center py-1 px-1.5 rounded-xl transition-all ${
                activeTab === tab.id ? 'text-[#B08968]' : 'text-[#8B8279]'
              }`}
            >
              <span className="text-xl">{tab.icon}</span>
              {activeTab === tab.id && <span className="text-[10px] font-medium mt-0.5">{tab.label}</span>}
            </button>
          ))}
        </div>
      </nav>
      
      {/* Отступ для нижнего меню */}
      <div className="sm:hidden h-20"></div>

      {/* Модалка пользователя */}
      {selectedUser && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={() => setSelectedUser(null)}>
          <div 
            className="bg-white rounded-2xl max-w-md w-full max-h-[80vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-5 border-b border-[#E8D4BA]/30">
              <div className="flex items-center gap-4">
                {selectedUser.user.photo_url ? (
                  <img src={selectedUser.user.photo_url} alt="" className="w-16 h-16 rounded-full" />
                ) : (
                  <div className="w-16 h-16 rounded-full bg-[#B08968] text-white text-2xl flex items-center justify-center font-medium">
                    {selectedUser.user.first_name?.charAt(0) || '?'}
                  </div>
                )}
                <div>
                  <h3 className="font-bold text-lg text-[#5D4E3A]">{selectedUser.user.first_name || 'Без имени'}</h3>
                  {selectedUser.user.username && (
                    <p className="text-sm text-[#8B8279]">@{selectedUser.user.username}</p>
                  )}
                  <div className="flex gap-2 mt-1">
                    <span className="text-xs px-2 py-0.5 rounded-full bg-[#F5E6D3]">
                      {selectedUser.has_push ? '🔔 Push вкл' : '⚪ Push выкл'}
                    </span>
                    {selectedUser.subscription_end && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700">
                        Подписка до {new Date(selectedUser.subscription_end).toLocaleDateString('ru-RU')}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
            
            <div className="p-5 space-y-4">
              {/* Последние просмотры */}
              <div>
                <h4 className="font-medium text-[#5D4E3A] mb-2">👁 Последние просмотры</h4>
                {selectedUser.views.length > 0 ? (
                  <div className="space-y-1">
                    {selectedUser.views.slice(0, 5).map((v, i) => (
                      <div key={i} className="text-sm flex justify-between">
                        <span className="text-[#5D4E3A] truncate flex-1">{v.title}</span>
                        <span className="text-[#8B8279] text-xs ml-2">
                          {new Date(v.viewed_at).toLocaleDateString('ru-RU')}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-[#8B8279]">Нет просмотров</p>
                )}
              </div>

              {/* Избранное */}
              <div>
                <h4 className="font-medium text-[#5D4E3A] mb-2">⭐ Избранное ({selectedUser.favorites.length})</h4>
                {selectedUser.favorites.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {selectedUser.favorites.map((f, i) => (
                      <span key={i} className="text-xs px-2 py-1 bg-[#F5E6D3] rounded-lg text-[#5D4E3A]">{f}</span>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-[#8B8279]">Пусто</p>
                )}
              </div>
            </div>

            <div className="p-5 border-t border-[#E8D4BA]/30 flex gap-2">
              {selectedUser.user.username && (
                <a
                  href={`https://t.me/${selectedUser.user.username}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex-1 py-2 bg-[#0088cc] text-white rounded-xl font-medium text-center"
                >
                  💬 Написать в Telegram
                </a>
              )}
              <button
                onClick={() => setSelectedUser(null)}
                className="px-4 py-2 border border-[#E8D4BA] text-[#8B8279] rounded-xl"
              >
                Закрыть
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
