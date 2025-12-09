'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import axios from 'axios'
import { usePresence, Activity as WsActivity, AdminAction as WsAdminAction } from '@/hooks/usePresence'
import { ADMIN_IDS, ADMIN_GROUP_INFO } from '@/lib/constants'
import { Category, Material, Stats, Activity, AdminAction, AdminUser } from '@/lib/types'
import { CategoriesTab, HistoryTab, UsersTab, MaterialsTab, MaterialFormModal, CategoryFormModal, StatsTab } from '@/components/admin'

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

// Типы импортированы из @/lib/types

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
  
  const [formErrors, setFormErrors] = useState<Record<string, string>>({}) // Валидация
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false) // Отслеживание изменений

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
      format: material.format || 'article',
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
    setFormErrors({})
    setHasUnsavedChanges(false)
  }

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
        {activeTab === 'stats' && (
          <StatsTab
            stats={stats}
            onlineUsers={onlineUsers}
            isConnected={isConnected}
            libraryCount={libraryCount}
            adminCount={adminCount}
            pushSubscribers={pushSubscribers}
            usersStats={usersStats}
            showPushForm={showPushForm}
            setShowPushForm={setShowPushForm}
            pushForm={pushForm}
            setPushForm={setPushForm}
            pushSending={pushSending}
            sendPush={sendPush}
            analytics={analytics}
            recentActivity={recentActivity}
            copiedUsername={copiedUsername}
            copyUsername={copyUsername}
          />
        )}

        {/* Materials Tab */}
        {activeTab === 'materials' && (
          <MaterialsTab
            materials={materials}
            categories={categories}
            loadingMaterials={loadingMaterials}
            onOpenForm={() => { resetForm(); setShowMaterialForm(true); }}
            onEdit={handleEditMaterial}
            onDelete={handleDeleteMaterial}
            onTogglePublish={handleTogglePublish}
          />
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
      <MaterialFormModal
        isOpen={showMaterialForm}
        editingMaterial={editingMaterial}
        categories={categories}
        formData={formData}
        formErrors={formErrors}
        hasUnsavedChanges={hasUnsavedChanges}
        uploadingCover={uploadingCover}
        onClose={handleCloseForm}
        onSubmit={handleSubmit}
        onUpdateFormData={updateFormData}
        onSetFormData={setFormData}
        onProcessImageFile={processImageFile}
      />

      {/* Category Form Modal */}
      <CategoryFormModal
        isOpen={showCategoryForm}
        editingCategory={editingCategory}
        categoryForm={categoryForm}
        onClose={() => setShowCategoryForm(false)}
        onSubmit={handleCategorySubmit}
        onFormChange={setCategoryForm}
      />
      
      {/* Users Tab */}
      {activeTab === 'users' && (
        <UsersTab
          usersStats={usersStats}
          onLoadUserDetails={loadUserDetails}
          onCopyUsername={copyUsername}
          copiedUsername={copiedUsername}
        />
      )}
      
      {/* Нижнее меню - только на мобилке, скрывается при открытых формах */}
      <nav 
        className={`sm:hidden fixed bottom-0 left-0 right-0 bg-white/70 backdrop-blur-2xl border-t border-[#E8D4BA]/20 px-2 py-2 z-50 transition-transform duration-300 ${
          isMenuVisible && !showMaterialForm && !showCategoryForm ? 'translate-y-0' : 'translate-y-full'
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
