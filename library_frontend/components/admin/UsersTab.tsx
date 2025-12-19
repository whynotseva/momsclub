'use client'

import { useState, useMemo } from 'react'
import { Bell, BellOff, Clock, Eye, Star } from 'lucide-react'

interface UserStats {
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
}

interface UsersTabProps {
  usersStats: UserStats | null
  onLoadUserDetails: (telegramId: number) => void
  onCopyUsername: (username: string) => void
  copiedUsername: string | null
}

type FilterType = 'all' | 'with_push' | 'no_push'
type SortType = 'recent' | 'most_views' | 'least_views'

/**
 * Таб управления пользователями в админке
 */
export function UsersTab({ usersStats, onLoadUserDetails, onCopyUsername, copiedUsername }: UsersTabProps) {
  const [usersFilter, setUsersFilter] = useState<FilterType>('all')
  const [usersSort, setUsersSort] = useState<SortType>('recent')
  const [usersLimit, setUsersLimit] = useState(10)

  const { filtered, displayed, hasMore } = useMemo(() => {
    const filtered = usersStats?.users
      .filter(u => {
        if (usersFilter === 'with_push') return u.has_push
        if (usersFilter === 'no_push') return !u.has_push
        return true
      })
      .sort((a, b) => {
        if (usersSort === 'most_views') return b.views_count - a.views_count
        if (usersSort === 'least_views') return a.views_count - b.views_count
        return 0 // recent - уже отсортировано с бэка
      }) || []
    
    return {
      filtered,
      displayed: filtered.slice(0, usersLimit),
      hasMore: filtered.length > usersLimit
    }
  }, [usersStats, usersFilter, usersSort, usersLimit])

  return (
    <div className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-2xl border border-[#E8D4BA]/30 dark:border-[#3D3D3D] overflow-hidden">
      <div className="p-4 border-b border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-[#5D4E3A] dark:text-[#E5E5E5]">Пользователи библиотеки</h3>
            {usersStats && (
              <span className="text-sm text-[#8B8279] dark:text-[#707070]">
                <>{usersStats.total} чел • {usersStats.with_push} <Bell className="w-3 h-3 inline" /></>
              </span>
            )}
          </div>
          {/* Фильтры */}
          <div className="flex flex-wrap gap-2">
            {(['all', 'with_push', 'no_push'] as const).map((filter) => (
              <button
                key={filter}
                onClick={() => { setUsersFilter(filter); setUsersLimit(10); }}
                className={`px-3 py-1.5 rounded-lg text-sm transition-all ${
                  usersFilter === filter
                    ? 'bg-[#B08968] text-white'
                    : 'bg-[#F5E6D3]/50 dark:bg-[#2A2A2A] text-[#8B8279] dark:text-[#B0B0B0] hover:bg-[#F5E6D3] dark:hover:bg-[#3D3D3D]'
                }`}
              >
                {filter === 'all' && 'Все'}
                {filter === 'with_push' && <><Bell className="w-3 h-3 inline" /> Push</>}
                {filter === 'no_push' && <><BellOff className="w-3 h-3 inline" /> Без</>}
              </button>
            ))}
            <span className="text-[#E8D4BA] self-center">|</span>
            {(['recent', 'most_views', 'least_views'] as const).map((sort) => (
              <button
                key={sort}
                onClick={() => { setUsersSort(sort); setUsersLimit(10); }}
                className={`px-3 py-1.5 rounded-lg text-sm transition-all ${
                  usersSort === sort
                    ? 'bg-[#B08968] text-white'
                    : 'bg-[#F5E6D3]/50 dark:bg-[#2A2A2A] text-[#8B8279] dark:text-[#B0B0B0] hover:bg-[#F5E6D3] dark:hover:bg-[#3D3D3D]'
                }`}
              >
                {sort === 'recent' && <><Clock className="w-3 h-3 inline" /> Недавние</>}
                {sort === 'most_views' && <><Eye className="w-3 h-3 inline" /> Больше</>}
                {sort === 'least_views' && <><Eye className="w-3 h-3 inline" /> Меньше</>}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="divide-y divide-[#E8D4BA]/20 dark:divide-[#3D3D3D]">
        {displayed.map((user) => (
          <div 
            key={user.id} 
            className="p-4 flex items-center gap-3 hover:bg-[#F5E6D3]/30 dark:hover:bg-[#2A2A2A] transition-colors cursor-pointer"
            onClick={() => onLoadUserDetails(user.telegram_id)}
          >
            {user.photo_url ? (
              <img src={user.photo_url} alt="" className="w-10 h-10 rounded-full" />
            ) : (
              <div className="w-10 h-10 rounded-full bg-[#B08968] text-white flex items-center justify-center font-medium">
                {user.first_name?.charAt(0) || '?'}
              </div>
            )}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-[#5D4E3A] dark:text-[#E5E5E5]">{user.first_name || 'Без имени'}</span>
                {user.has_push ? <Bell className="w-4 h-4 text-[#B08968]" /> : <BellOff className="w-4 h-4 text-gray-300" />}
              </div>
              {user.username && (
                <button
                  onClick={(e) => { e.stopPropagation(); onCopyUsername(user.username!); }}
                  className="text-sm text-[#8B8279] hover:text-[#B08968] transition-colors"
                >
                  @{user.username} {copiedUsername === user.username && '✓'}
                </button>
              )}
            </div>
            <div className="text-right text-sm">
              <p className="text-[#5D4E3A] dark:text-[#E5E5E5] flex items-center gap-1">{user.views_count} <Eye className="w-3 h-3" /></p>
              <p className="text-[#8B8279] dark:text-[#707070] flex items-center gap-1">{user.favorites_count} <Star className="w-3 h-3" /></p>
            </div>
          </div>
        ))}
        {hasMore && (
          <button
            onClick={() => setUsersLimit(prev => prev + 10)}
            className="w-full p-4 text-center text-[#B08968] hover:bg-[#F5E6D3]/30 dark:hover:bg-[#2A2A2A] transition-colors font-medium"
          >
            Показать ещё ({filtered.length - usersLimit} осталось)
          </button>
        )}
        {usersLimit > 10 && (
          <button
            onClick={() => setUsersLimit(10)}
            className="w-full p-3 text-center text-[#8B8279] dark:text-[#707070] hover:bg-[#F5E6D3]/30 dark:hover:bg-[#2A2A2A] transition-colors text-sm"
          >
            Свернуть
          </button>
        )}
        {!usersStats && <div className="p-8 text-center text-[#8B8279] dark:text-[#707070]">Загрузка...</div>}
      </div>
    </div>
  )
}
