'use client'

import { useState, useCallback } from 'react'
import axios from 'axios'
import { Category, Material, Stats, Activity, AdminAction } from '@/lib/types'

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

// Типы для хука
interface UserWithPush {
  id: number
  telegram_id: number
  first_name: string
  username?: string
  photo_url?: string
  views_count: number
  favorites_count: number
  last_activity?: string
  has_push: boolean
}

interface UsersStats {
  users: UserWithPush[]
  total: number
  with_push: number
}

interface Analytics {
  views_by_day: { day: string; count: number }[]
  top_materials: { id: number; title: string; views: number }[]
  avg_duration_seconds: number
}

interface SelectedUser {
  user: { id: number; telegram_id: number; first_name: string; username?: string; photo_url?: string }
  views: { title: string; viewed_at: string }[]
  favorites: string[]
  subscription_end?: string
  has_push: boolean
}

interface BotUser {
  id: number
  telegram_id: number
  username?: string
  first_name?: string
  last_name?: string
  created_at: string
  subscription?: { end_date: string; days_left: number; price: number }
  has_active_subscription: boolean
  is_recurring_active: boolean
  autopay_streak: number
  loyalty: { level: string; days_in_club: number }
  referral: { referral_balance: number; referrals_count: number; total_earned_referral: number }
  badges: { badge_type: string }[]
  total_payments_count: number
  total_paid_amount: number
}

/**
 * Хук для загрузки данных админки
 */
export function useAdminData() {
  // Основные данные
  const [stats, setStats] = useState<Stats | null>(null)
  const [materials, setMaterials] = useState<Material[]>([])
  const [loadingMaterials, setLoadingMaterials] = useState(false)
  const [categories, setCategories] = useState<Category[]>([])
  const [recentActivity, setRecentActivity] = useState<Activity[]>([])
  const [adminHistory, setAdminHistory] = useState<AdminAction[]>([])
  const [loadingHistory, setLoadingHistory] = useState(false)
  
  // Push и пользователи
  const [pushSubscribers, setPushSubscribers] = useState<number[]>([])
  const [usersStats, setUsersStats] = useState<UsersStats | null>(null)
  const [analytics, setAnalytics] = useState<Analytics | null>(null)
  const [selectedUser, setSelectedUser] = useState<SelectedUser | null>(null)
  const [selectedBotUser, setSelectedBotUser] = useState<BotUser | null>(null)
  
  // Утилиты
  const [copiedUsername, setCopiedUsername] = useState<string | null>(null)

  // === ФУНКЦИИ ЗАГРУЗКИ ===

  const loadRecentActivity = useCallback(async () => {
    try {
      const response = await api.get('/activity/recent?limit=15')
      setRecentActivity(response.data)
    } catch (error) {
      console.error('Error loading activity:', error)
    }
  }, [])

  const loadStats = useCallback(async () => {
    try {
      const response = await api.get('/admin/stats')
      setStats(response.data)
      loadRecentActivity()
    } catch (error) {
      console.error('Error loading stats:', error)
      setStats({
        materials: { total: 0, published: 0, drafts: 0 },
        views_total: 0,
        favorites_total: 0,
        categories_total: 0
      })
    }
  }, [loadRecentActivity])

  const loadMaterials = useCallback(async () => {
    setLoadingMaterials(true)
    try {
      const response = await api.get('/materials?include_drafts=true&page_size=200')
      setMaterials(response.data.items || [])
    } catch (error) {
      console.error('Error loading materials:', error)
      setMaterials([])
    } finally {
      setLoadingMaterials(false)
    }
  }, [])

  const loadCategories = useCallback(async () => {
    try {
      const response = await api.get('/categories')
      setCategories(response.data)
    } catch (error) {
      console.error('Error loading categories:', error)
    }
  }, [])

  const loadPushSubscribers = useCallback(async () => {
    try {
      const response = await api.get('/push/subscribers')
      setPushSubscribers(response.data.subscribers || [])
    } catch (error) {
      console.error('Error loading push subscribers:', error)
    }
  }, [])

  const loadUsersStats = useCallback(async () => {
    try {
      const response = await api.get('/push/users-stats')
      setUsersStats(response.data)
    } catch (error) {
      console.error('Error loading users stats:', error)
    }
  }, [])

  const loadAnalytics = useCallback(async () => {
    try {
      const response = await api.get('/push/analytics')
      setAnalytics(response.data)
    } catch (error) {
      console.error('Error loading analytics:', error)
    }
  }, [])

  const loadUserDetails = useCallback(async (telegramId: number) => {
    try {
      const response = await api.get(`/push/user-details/${telegramId}`)
      setSelectedUser(response.data)
    } catch (error) {
      console.error('Error loading user details:', error)
    }
  }, [])

  const loadAdminHistory = useCallback(async () => {
    setLoadingHistory(true)
    try {
      const response = await api.get('/activity/admin-history?limit=50')
      setAdminHistory(response.data)
    } catch (error) {
      console.error('Error loading admin history:', error)
    } finally {
      setLoadingHistory(false)
    }
  }, [])

  // === УТИЛИТЫ ===

  const copyUsername = useCallback((username: string) => {
    navigator.clipboard.writeText(`@${username}`)
    setCopiedUsername(username)
    setTimeout(() => setCopiedUsername(null), 2000)
  }, [])

  const closeUserDetails = useCallback(() => {
    setSelectedUser(null)
  }, [])

  const loadBotUserDetails = useCallback(async (telegramId: number) => {
    try {
      const response = await api.get(`/admin/users/${telegramId}`)
      setSelectedBotUser(response.data)
    } catch (error) {
      console.error('Failed to load bot user:', error)
    }
  }, [])

  const closeBotUserDetails = useCallback(() => {
    setSelectedBotUser(null)
  }, [])

  const addActivity = useCallback((activity: Activity) => {
    setRecentActivity(prev => [activity, ...prev].slice(0, 20))
  }, [])

  const addAdminAction = useCallback((action: AdminAction) => {
    setAdminHistory(prev => [action, ...prev].slice(0, 50))
  }, [])

  const updateCategories = useCallback((newCategories: Category[]) => {
    setCategories(newCategories)
  }, [])

  return {
    // Данные
    stats, materials, loadingMaterials, categories,
    recentActivity, adminHistory, loadingHistory,
    pushSubscribers, usersStats, analytics, selectedUser, selectedBotUser, copiedUsername,
    
    // Функции загрузки
    loadStats, loadMaterials, loadCategories, loadRecentActivity,
    loadPushSubscribers, loadUsersStats, loadAnalytics, loadUserDetails, loadAdminHistory,
    loadBotUserDetails,
    
    // Утилиты
    copyUsername, closeUserDetails, closeBotUserDetails, addActivity, addAdminAction, updateCategories,
    
    // API
    api,
  }
}
