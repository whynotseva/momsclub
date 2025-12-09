'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { api } from '@/lib/api'
import { Material } from '@/lib/types'
import { ADMIN_IDS } from '@/lib/constants'
import { useScrollVisibility } from '@/hooks/useScrollVisibility'

export default function HistoryPage() {
  const router = useRouter()
  const [loading, setLoading] = useState(true)
  const [history, setHistory] = useState<Material[]>([])
  const [favoriteIds, setFavoriteIds] = useState<Set<number>>(new Set())
  const [user, setUser] = useState({ name: '', avatar: '' })
  const [isAdmin, setIsAdmin] = useState(false)
  const [showProfileMenu, setShowProfileMenu] = useState(false)
  const isVisible = useScrollVisibility()

  useEffect(() => {
    const loadData = async () => {
      const token = localStorage.getItem('access_token')
      if (!token) {
        router.push('/login')
        return
      }

      try {
        // Проверяем подписку
        const subResponse = await api.get('/auth/check-subscription')
        if (!subResponse.data.has_active_subscription) {
          localStorage.removeItem('access_token')
          localStorage.removeItem('user')
          alert('Ваша подписка истекла. Продлите подписку через @momsclubsubscribe_bot')
          router.push('/login')
          return
        }

        const [histResponse, favResponse, meResponse] = await Promise.all([
          api.get('/materials/history/my'),
          api.get('/materials/favorites/my'),
          api.get('/auth/me')
        ])
        setHistory(histResponse.data || [])
        setFavoriteIds(new Set((favResponse.data || []).map((m: Material) => m.id)))
        const userData = meResponse.data
        setUser({
          name: userData.first_name || 'Гость',
          avatar: userData.photo_url || `https://api.dicebear.com/7.x/avataaars/svg?seed=${userData.username}&backgroundColor=ffdfbf`
        })
        if (ADMIN_IDS.includes(userData.telegram_id)) setIsAdmin(true)
      } catch (error) {
        console.error('Error loading history:', error)
        localStorage.removeItem('access_token')
        localStorage.removeItem('user')
        router.push('/login')
        return
      }
      setLoading(false)
    }
    loadData()
  }, [router])

  const openMaterial = async (material: Material) => {
    try {
      await api.post(`/materials/${material.id}/view`)
    } catch (error) {
      console.error('Error recording view:', error)
    }
    if (material.external_url) {
      window.open(material.external_url, '_blank')
    }
  }

  const toggleFavorite = async (id: number) => {
    const isFav = favoriteIds.has(id)
    try {
      if (isFav) {
        await api.delete(`/materials/${id}/favorite`)
        setFavoriteIds(prev => { const s = new Set(prev); s.delete(id); return s })
      } else {
        await api.post(`/materials/${id}/favorite`)
        setFavoriteIds(prev => new Set(prev).add(id))
      }
    } catch (error) {
      console.error('Error toggling favorite:', error)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-[#FDFCFA] via-[#FBF8F3] to-[#F5EFE6] flex items-center justify-center">
        <p className="text-[#8B8279]">Загрузка...</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#FDFCFA] via-[#FBF8F3] to-[#F5EFE6] relative">
      <div className="fixed -top-40 -right-40 w-[600px] h-[600px] bg-gradient-to-br from-[#E8D5C4]/30 via-[#D4C4B0]/15 to-transparent rounded-full blur-3xl pointer-events-none"></div>
      <div className="fixed -bottom-40 -left-40 w-[500px] h-[500px] bg-gradient-to-tr from-[#C9B89A]/15 to-transparent rounded-full blur-3xl pointer-events-none"></div>

      <header className={`fixed top-0 left-0 right-0 z-50 border-b border-white/50 shadow-lg transition-transform duration-300 ease-in-out ${isVisible ? 'translate-y-0' : '-translate-y-full'}`} style={{ background: 'rgba(255,255,255,0.55)', backdropFilter: 'blur(20px) saturate(180%)', paddingTop: 'env(safe-area-inset-top)' }}>
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <a href="/library" className="flex items-center space-x-3 group">
              <img src="/logolibrary.svg" alt="LibriMomsClub" className="h-10 w-auto group-hover:scale-105 transition-transform" />
            </a>
            <nav className="hidden md:flex space-x-8">
              <a href="/library" className="text-[#8B8279] hover:text-[#B08968] transition-colors">Библиотека</a>
              <a href="/favorites" className="text-[#8B8279] hover:text-[#B08968] transition-colors">Избранное</a>
              <a href="/history" className="text-[#B08968] font-semibold">История</a>
            </nav>
            <div className="flex items-center space-x-4">
              <div className="relative">
                <button onClick={() => setShowProfileMenu(!showProfileMenu)} className="flex items-center space-x-2">
                  <img src={user.avatar} alt={user.name} className="w-9 h-9 rounded-full border-2 border-[#E8D4BA] object-cover hover:border-[#B08968] transition-colors" />
                  <span className="text-[#8B8279] text-sm font-medium hidden md:block">Выйти</span>
                </button>
                {showProfileMenu && (
                  <div className="absolute right-0 top-12 bg-white rounded-xl shadow-xl border border-[#E8D4BA]/50 py-2 min-w-[160px] z-50">
                    <div className="px-4 py-2 border-b border-gray-100">
                      <p className="text-sm font-medium text-[#2D2A26]">{user.name}</p>
                    </div>
                    {isAdmin && (
                      <Link href="/admin" className="block w-full px-4 py-2 text-left text-sm text-[#B08968] hover:bg-[#F5E6D3] transition-colors">
                        ⚙️ Админ-панель
                      </Link>
                    )}
                    <button onClick={() => { localStorage.removeItem('access_token'); localStorage.removeItem('user'); router.push('/login') }} className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50">
                      🚪 Выйти
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8" style={{ paddingTop: 'calc(5rem + env(safe-area-inset-top, 0px))' }}>
        <div className="mb-8">
          <h2 className="text-3xl font-bold text-[#2D2A26] mb-2">📖 История просмотров</h2>
          <p className="text-[#5C5650]">Материалы, которые ты недавно смотрел</p>
        </div>
        
        {history.length === 0 ? (
          <div className="bg-white/90 rounded-3xl p-16 text-center shadow-xl shadow-[#C9A882]/10 border border-[#E8D4BA]/40">
            <div className="text-6xl mb-6">📚</div>
            <h3 className="text-xl font-bold text-[#2D2A26] mb-2">История пуста</h3>
            <p className="text-[#8B8279] mb-6">Начни изучать материалы, и они появятся здесь</p>
            <a href="/library" className="inline-flex items-center px-6 py-3 bg-gradient-to-r from-[#B08968] to-[#A67C52] text-white font-semibold rounded-xl hover:shadow-lg transition-all">
              Перейти в библиотеку
            </a>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {history.map((material) => (
              <div key={material.id} className="group bg-white/90 rounded-2xl shadow-lg shadow-[#C9A882]/10 hover:shadow-xl transition-all p-5 border border-[#E8D4BA]/40 hover:-translate-y-1 relative overflow-hidden">
                <button onClick={() => toggleFavorite(material.id)} className={`absolute bottom-4 right-4 z-10 w-9 h-9 rounded-full flex items-center justify-center shadow-md ${favoriteIds.has(material.id) ? 'bg-red-500 text-white' : 'bg-white/90 text-gray-400'}`}>
                  <span className="text-lg">{favoriteIds.has(material.id) ? '❤️' : '🤍'}</span>
                </button>
                <div onClick={() => openMaterial(material)} className="cursor-pointer">
                  {(material.cover_url || material.cover_image) ? (
                    <img src={material.cover_url || material.cover_image} alt={material.title} className="w-full h-24 object-cover rounded-xl mb-3" />
                  ) : (
                    <div className="w-full h-24 bg-gradient-to-br from-[#C9A882] to-[#B08968] rounded-xl mb-3 flex items-center justify-center text-3xl">
                      {material.category?.icon || '📄'}
                    </div>
                  )}
                  <span className="text-xs bg-[#F5E6D3] text-[#8B7355] px-2 py-1 rounded-full font-medium">{material.category?.name || material.format}</span>
                  <h4 className="font-semibold text-[#2D2A26] mt-2 text-sm leading-tight line-clamp-2">{material.title}</h4>
                  <div className="text-xs text-[#8B8279] mt-2">👁️ {material.views} {material.external_url && '🔗'}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      <nav className={`md:hidden fixed bottom-6 left-4 right-4 z-50 transition-all duration-300 ease-in-out ${isVisible ? 'translate-y-0 opacity-100' : 'translate-y-24 opacity-0'}`}>
        <div className="flex items-center justify-around rounded-2xl px-2 py-3 shadow-2xl border border-white/50" style={{ background: 'rgba(255,255,255,0.45)', backdropFilter: 'blur(24px) saturate(180%)' }}>
          <a href="/library" className="px-4 py-2 rounded-xl text-[#8B8279] text-sm font-medium">Библиотека</a>
          <a href="/favorites" className="px-4 py-2 rounded-xl text-[#8B8279] text-sm font-medium">Избранное</a>
          <a href="/history" className="px-4 py-2 rounded-xl bg-[#B08968] text-white text-sm font-semibold shadow-md">История</a>
        </div>
      </nav>
    </div>
  )
}
