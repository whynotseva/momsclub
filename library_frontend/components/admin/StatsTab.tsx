'use client'

import { ADMIN_GROUP_INFO } from '@/lib/constants'
import { Avatar } from '@/components/shared'
import { BookOpen, Eye, Star, FolderOpen, Bell, BellOff, Trophy, ClipboardList, Users, Settings, HeartOff, Crown, Code, Target } from 'lucide-react'

// Типы
interface OnlineUser {
  telegram_id: number
  first_name?: string
  username?: string
  admin_group?: string
  photo_url?: string
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
    first_name?: string
    username?: string
    photo_url?: string
  }
  material: {
    id: number
    title: string
    icon: string
  }
}

interface UserWithPush {
  id: number
  telegram_id: number
  first_name?: string
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

interface PushForm {
  title: string
  body: string
  url: string
  targetUser: string
}

interface StatsTabProps {
  stats: Stats | null
  // Онлайн пользователи
  onlineUsers: { library: OnlineUser[]; admin: OnlineUser[] }
  isConnected: boolean
  libraryCount: number
  adminCount: number
  // Push
  pushSubscribers: number[]
  usersStats: UsersStats | null
  showPushForm: boolean
  setShowPushForm: (show: boolean) => void
  pushForm: PushForm
  setPushForm: (form: PushForm) => void
  pushSending: boolean
  sendPush: (toAll: boolean) => void
  // Аналитика
  analytics: Analytics | null
  recentActivity: Activity[]
  // Утилиты
  copiedUsername: string | null
  copyUsername: (username: string) => void
}

/**
 * Вкладка статистики в админке
 * Показывает: онлайн пользователей, статистику, push-рассылку, топ материалов, ленту активности
 */
export function StatsTab({
  stats,
  onlineUsers,
  isConnected,
  libraryCount,
  adminCount,
  pushSubscribers,
  usersStats,
  showPushForm,
  setShowPushForm,
  pushForm,
  setPushForm,
  pushSending,
  sendPush,
  analytics,
  recentActivity,
  copiedUsername,
  copyUsername,
}: StatsTabProps) {
  return (
    <>
      {/* Виджет онлайн пользователей */}
      <div className="mb-6 grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* В библиотеке */}
        <div className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-2xl p-4 border border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-medium text-[#5D4E3A] dark:text-[#E5E5E5] flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-[#B08968]" /> В библиотеке
              <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-gray-300'}`}></span>
            </h3>
            <span className="text-sm text-[#8B8279] dark:text-[#707070]">{libraryCount} онлайн</span>
          </div>
          {onlineUsers.library.length > 0 ? (
            <div className="space-y-2 max-h-[200px] overflow-y-auto">
              {onlineUsers.library.slice(0, 8).map((user) => (
                <div 
                  key={user.telegram_id} 
                  className="flex items-center gap-2 bg-[#F5E6D3]/50 dark:bg-[#2A2A2A] rounded-lg px-3 py-2"
                >
                  <Avatar src={user.photo_url} name={user.first_name} size="sm" />
                  <div className="flex-1 min-w-0">
                    <span className="text-sm text-[#5D4E3A] dark:text-[#E5E5E5] font-medium truncate block">{user.first_name}</span>
                    {user.username && (
                      <button 
                        onClick={() => copyUsername(user.username!)}
                        className="text-xs text-[#8B8279] hover:text-[#B08968] transition-colors"
                      >
                        @{user.username} {copiedUsername === user.username && '✓'}
                      </button>
                    )}
                  </div>
                  <span title={pushSubscribers.includes(user.telegram_id) ? 'Push вкл' : 'Push выкл'}>
                    {pushSubscribers.includes(user.telegram_id) ? <Bell className="w-4 h-4 text-[#B08968]" /> : <BellOff className="w-4 h-4 text-gray-300" />}
                  </span>
                </div>
              ))}
              {onlineUsers.library.length > 8 && (
                <p className="text-xs text-[#8B8279] text-center">+{onlineUsers.library.length - 8} ещё</p>
              )}
            </div>
          ) : (
            <p className="text-sm text-[#8B8279] dark:text-[#707070]">Никого нет онлайн</p>
          )}
        </div>

        {/* В админке */}
        <div className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-2xl p-4 border border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-medium text-[#5D4E3A] dark:text-[#E5E5E5] flex items-center gap-2">
              <Settings className="w-5 h-5 text-[#B08968]" /> В админке
              <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-gray-300'}`}></span>
            </h3>
            <span className="text-sm text-[#8B8279] dark:text-[#707070]">{adminCount} онлайн</span>
          </div>
          {onlineUsers.admin.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {onlineUsers.admin.map((user) => (
                <div 
                  key={user.telegram_id} 
                  className="flex items-center gap-2 bg-gradient-to-r from-amber-50 to-orange-50 dark:from-[#2A2A2A] dark:to-[#2A2A2A] rounded-lg px-2 py-1 border border-amber-200/50 dark:border-[#3D3D3D]"
                  title={`${user.first_name}${user.admin_group ? ` (${ADMIN_GROUP_INFO[user.admin_group]?.name || ''})` : ''}`}
                >
                  <Avatar src={user.photo_url} name={user.first_name} size="sm" className="w-6 h-6" />
                  <span className="text-xs text-[#5D4E3A] dark:text-[#E5E5E5] font-medium">{user.first_name}</span>
                  {user.admin_group === 'creator' && <Crown className="w-3 h-3 text-amber-500" />}
                  {user.admin_group === 'developer' && <Code className="w-3 h-3 text-blue-500" />}
                  {user.admin_group === 'curator' && <Target className="w-3 h-3 text-green-500" />}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-[#8B8279] dark:text-[#707070]">Никого нет онлайн</p>
          )}
        </div>
      </div>

      {/* Статистика */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-2xl p-6 border border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-gradient-to-br from-blue-400 to-blue-500 rounded-xl flex items-center justify-center">
                <BookOpen className="w-6 h-6 text-white" />
              </div>
              <div>
                <p className="text-2xl font-bold text-[#5D4E3A] dark:text-[#E5E5E5]">{stats.materials.total}</p>
                <p className="text-sm text-[#8B8279] dark:text-[#707070]">Материалов</p>
              </div>
            </div>
            <div className="mt-4 flex gap-4 text-xs">
              <span className="text-green-600 dark:text-green-400">✓ {stats.materials.published} опубл.</span>
              <span className="text-orange-500 dark:text-orange-400">◐ {stats.materials.drafts} черновик</span>
            </div>
          </div>

          <div className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-2xl p-6 border border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-gradient-to-br from-purple-400 to-purple-500 rounded-xl flex items-center justify-center">
                <Eye className="w-6 h-6 text-white" />
              </div>
              <div>
                <p className="text-2xl font-bold text-[#5D4E3A] dark:text-[#E5E5E5]">{stats.views_total}</p>
                <p className="text-sm text-[#8B8279] dark:text-[#707070]">Просмотров</p>
              </div>
            </div>
          </div>

          <div className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-2xl p-6 border border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-gradient-to-br from-pink-400 to-pink-500 rounded-xl flex items-center justify-center">
                <Star className="w-6 h-6 text-white" />
              </div>
              <div>
                <p className="text-2xl font-bold text-[#5D4E3A] dark:text-[#E5E5E5]">{stats.favorites_total}</p>
                <p className="text-sm text-[#8B8279] dark:text-[#707070]">В избранном</p>
              </div>
            </div>
          </div>

          <div className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-2xl p-6 border border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-gradient-to-br from-amber-400 to-amber-500 rounded-xl flex items-center justify-center">
                <FolderOpen className="w-6 h-6 text-white" />
              </div>
              <div>
                <p className="text-2xl font-bold text-[#5D4E3A] dark:text-[#E5E5E5]">{stats.categories_total}</p>
                <p className="text-sm text-[#8B8279] dark:text-[#707070]">Категорий</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Push-рассылка и Аналитика */}
      <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Кнопка Push */}
        <div className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-2xl p-5 border border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-[#5D4E3A] dark:text-[#E5E5E5] flex items-center gap-2">
              <Bell className="w-5 h-5 text-[#B08968]" /> Push-рассылка
            </h3>
            <span className="text-sm text-[#8B8279] dark:text-[#707070]">{usersStats?.with_push || 0} подписчиков</span>
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
                    <Users className="w-4 h-4" /> Всем ({usersStats?.with_push || 0})
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
                      <Avatar src={u.photo_url} name={u.first_name || '?'} size="sm" />
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
        <div className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-2xl p-5 border border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
          <h3 className="font-semibold text-[#5D4E3A] dark:text-[#E5E5E5] mb-4 flex items-center gap-2">
            <Trophy className="w-5 h-5 text-[#B08968]" /> Топ за неделю
          </h3>
          {analytics?.top_materials.length ? (
            <div className="space-y-2">
              {analytics.top_materials.map((m, i) => (
                <div key={m.id} className="flex items-center gap-3 p-2 rounded-lg hover:bg-[#F5E6D3]/30 dark:hover:bg-[#2A2A2A]">
                  <span className={`text-sm font-bold w-6 h-6 rounded-full flex items-center justify-center ${i === 0 ? 'bg-yellow-100 text-yellow-600' : i === 1 ? 'bg-gray-100 text-gray-500' : i === 2 ? 'bg-orange-100 text-orange-500' : 'bg-[#F5E6D3] text-[#8B8279]'}`}>{i + 1}</span>
                  <span className="flex-1 text-sm text-[#5D4E3A] dark:text-[#E5E5E5] truncate">{m.title}</span>
                  <span className="text-sm text-[#8B8279] dark:text-[#707070] flex items-center gap-1">{m.views} <Eye className="w-3 h-3" /></span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-[#8B8279] dark:text-[#707070]">Нет данных</p>
          )}
        </div>
      </div>

      {/* Лента активности */}
      {recentActivity.length > 0 && (
        <div className="mt-6 bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-2xl p-5 border border-[#E8D4BA]/30 dark:border-[#3D3D3D] overflow-hidden">
          <h3 className="font-semibold text-[#5D4E3A] dark:text-[#E5E5E5] mb-4 flex items-center gap-2">
            <ClipboardList className="w-5 h-5 text-[#B08968]" /> Последние действия
          </h3>
          <div className="space-y-3 max-h-[400px] overflow-y-auto overflow-x-hidden">
            {recentActivity.map((activity, index) => (
              <div 
                key={index}
                className="flex items-center gap-3 p-3 bg-[#F5E6D3]/30 dark:bg-[#2A2A2A] rounded-xl hover:bg-[#F5E6D3]/50 dark:hover:bg-[#3D3D3D] transition-colors"
              >
                {/* Аватар */}
                <Avatar src={activity.user.photo_url} name={activity.user.first_name} size="md" />
                
                {/* Контент */}
                <div className="flex-1 min-w-0 overflow-hidden">
                  <p className="text-sm text-[#5D4E3A] dark:text-[#E5E5E5] truncate">
                    <span className="font-medium">{activity.user.first_name}</span>
                    <span className="text-[#8B8279] dark:text-[#B0B0B0]">
                      {activity.type === 'view' && ' открыл(а) '}
                      {activity.type === 'favorite_add' && ' добавил(а) в избранное '}
                      {activity.type === 'favorite_remove' && ' убрал(а) из избранного '}
                      {activity.type === 'favorite' && ' добавил(а) в избранное '}
                    </span>
                  </p>
                  <p className="text-sm text-[#5D4E3A] dark:text-[#E5E5E5] font-medium truncate">
                    {activity.material.icon} {activity.material.title}
                  </p>
                  <p className="text-xs text-[#8B8279] dark:text-[#707070] mt-0.5">
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
                  {activity.type === 'view' && <Eye className="w-4 h-4" />}
                  {activity.type === 'favorite_add' && <Star className="w-4 h-4" />}
                  {activity.type === 'favorite_remove' && <HeartOff className="w-4 h-4" />}
                  {activity.type === 'favorite' && <Star className="w-4 h-4" />}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}
