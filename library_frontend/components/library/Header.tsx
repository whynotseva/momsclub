'use client'

import Link from 'next/link'
import { Avatar } from '@/components/shared'

interface Notification {
  id: number
  type: string
  title: string
  text: string
  link?: string
  is_read: boolean
  created_at: string
}

interface HeaderProps {
  user: {
    name: string
    avatar: string
    notifications: number
  }
  isAdmin: boolean
  isVisible: boolean
  notifications: Notification[]
  showNotifications: boolean
  showProfileMenu: boolean
  pushSupported: boolean
  pushSubscribed: boolean
  pushLoading: boolean
  onToggleNotifications: () => void
  onToggleProfileMenu: () => void
  onTogglePush: () => void
  onMarkAsRead: (id: number) => void
  onMarkAllAsRead: () => void
  onLogout: () => void
}

/**
 * Хедер с навигацией, уведомлениями и профилем
 */
export function Header({
  user,
  isAdmin,
  isVisible,
  notifications,
  showNotifications,
  showProfileMenu,
  pushSupported,
  pushSubscribed,
  pushLoading,
  onToggleNotifications,
  onToggleProfileMenu,
  onTogglePush,
  onMarkAsRead,
  onMarkAllAsRead,
  onLogout,
}: HeaderProps) {
  return (
    <header 
      className={`fixed top-0 left-0 right-0 z-50 border-b border-white/50 shadow-lg transition-transform duration-300 ease-in-out ${isVisible ? 'translate-y-0' : '-translate-y-full'}`} 
      style={{ background: 'rgba(255,255,255,0.55)', backdropFilter: 'blur(20px) saturate(180%)', paddingTop: 'env(safe-area-inset-top)' }}
    >
      <div className="max-w-7xl mx-auto px-6 py-2">
        <div className="flex items-center justify-between">
          <a href="/library" className="flex items-center space-x-2 group relative">
            <span className="text-2xl absolute -top-1 -left-2 rotate-[-15deg] drop-shadow-md">🎅</span>
            <img 
              src="/logolibrary.svg" 
              alt="LibriMomsClub" 
              className="h-8 w-auto group-hover:scale-105 transition-transform ml-5"
            />
          </a>
          
          <nav className="hidden md:flex space-x-8">
            <a href="/library" className="text-[#B08968] font-semibold">Библиотека</a>
            <a href="/favorites" className="text-[#8B8279] hover:text-[#B08968] transition-colors">Избранное</a>
            <a href="/history" className="text-[#8B8279] hover:text-[#B08968] transition-colors">История</a>
          </nav>
          
          <div className="flex items-center space-x-4">
            {/* Уведомления */}
            <div className="relative">
              <button 
                onClick={onToggleNotifications}
                className="relative p-2 hover:bg-[#F5E6D3]/50 rounded-xl transition-colors"
              >
                <svg className="w-6 h-6 text-[#B08968]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                </svg>
                {user.notifications > 0 && (
                  <span className="absolute -top-1 -right-1 w-5 h-5 bg-red-500 text-white text-xs font-bold rounded-full flex items-center justify-center animate-pulse">
                    {user.notifications}
                  </span>
                )}
              </button>
              
              {/* Overlay для закрытия dropdown */}
              {showNotifications && (
                <div 
                  className="fixed inset-0 z-40 bg-black/5" 
                  onClick={onToggleNotifications}
                />
              )}
              
              {/* Dropdown уведомлений */}
              {showNotifications && (
                <div className="absolute right-0 top-12 w-80 bg-white rounded-2xl shadow-2xl border border-[#E8D4BA]/40 z-50 overflow-hidden">
                  {/* Header */}
                  <div className="px-4 py-3 border-b border-[#E8D4BA]/30 flex items-center justify-between">
                    <span className="font-bold text-[#2D2A26]">Уведомления</span>
                    <button 
                      onClick={onMarkAllAsRead}
                      className="text-xs text-[#B08968] hover:text-[#8B7355] font-medium"
                    >
                      Прочитать все
                    </button>
                  </div>
                  
                  {/* Notifications list */}
                  <div className="max-h-80 overflow-y-auto">
                    {notifications.length === 0 ? (
                      <div className="px-4 py-8 text-center text-[#8B8279]">
                        <span className="text-3xl mb-2 block">✨</span>
                        Нет новых уведомлений
                      </div>
                    ) : (
                      notifications.map((notif) => (
                        <div 
                          key={notif.id}
                          onClick={() => onMarkAsRead(notif.id)}
                          className={`px-4 py-3 border-b border-[#E8D4BA]/20 hover:bg-[#FBF8F3] cursor-pointer transition-colors ${
                            !notif.is_read ? 'bg-[#F5E6D3]/20' : ''
                          }`}
                        >
                          <div className="flex items-start space-x-3">
                            <div className={`w-2 h-2 rounded-full mt-2 flex-shrink-0 ${
                              !notif.is_read ? 'bg-[#B08968]' : 'bg-gray-300'
                            }`}></div>
                            <div className="flex-1">
                              <p className="font-semibold text-sm text-[#2D2A26]">{notif.title}</p>
                              <p className="text-sm text-[#5C5650]">{notif.text}</p>
                              <p className="text-xs text-[#8B8279] mt-1">
                                {new Date(notif.created_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
                              </p>
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                  
                  {/* Footer с Push toggle */}
                  <div className="px-4 py-3 border-t border-[#E8D4BA]/30">
                    {pushSupported && (
                      <button 
                        onClick={onTogglePush}
                        disabled={pushLoading}
                        className={`w-full mb-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2 ${
                          pushSubscribed 
                            ? 'bg-green-100 text-green-700 hover:bg-green-200' 
                            : 'bg-[#F5E6D3] text-[#8B7355] hover:bg-[#E8D4BA]'
                        }`}
                      >
                        {pushLoading ? (
                          '⏳ Загрузка...'
                        ) : pushSubscribed ? (
                          <>✅ Push включены (нажми чтобы отключить)</>
                        ) : (
                          <><svg className="w-4 h-4 inline mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" /></svg> Включить Push</>
                        )}
                      </button>
                    )}
                    <button 
                      onClick={onToggleNotifications}
                      className="w-full text-sm text-[#B08968] hover:text-[#8B7355] font-medium"
                    >
                      Закрыть
                    </button>
                  </div>
                </div>
              )}
            </div>
            
            {/* Аватар с выпадающим меню */}
            <div className="relative">
              <button
                onClick={onToggleProfileMenu}
                className="flex items-center space-x-2"
              >
                <Avatar 
                  src={user.avatar} 
                  name={user.name}
                  size="md"
                />
                <span className="text-[#8B8279] text-sm font-medium hidden md:block">
                  Выйти
                </span>
              </button>
              
              {/* Выпадающее меню профиля */}
              {showProfileMenu && (
                <div className="absolute right-0 top-12 bg-white rounded-xl shadow-xl border border-[#E8D4BA]/50 py-2 min-w-[160px] z-50">
                  <div className="px-4 py-2 border-b border-gray-100">
                    <p className="text-sm font-medium text-[#2D2A26]">{user.name}</p>
                    <p className="text-xs text-[#8B8279]">@{typeof window !== 'undefined' && localStorage.getItem('user') ? JSON.parse(localStorage.getItem('user') || '{}').username : ''}</p>
                  </div>
                  {isAdmin && (
                    <Link 
                      href="/admin"
                      className="w-full px-4 py-2 text-left text-sm text-[#B08968] hover:bg-[#F5E6D3] transition-colors flex items-center gap-2"
                    >
                      <span>⚙️</span> Админ-панель
                    </Link>
                  )}
                  <button 
                    onClick={onLogout}
                    className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 transition-colors flex items-center gap-2"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                    </svg>
                    Выйти
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </header>
  )
}
