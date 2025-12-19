'use client'

import { useState } from 'react'
import { Search, Loader2 } from 'lucide-react'

interface SearchResult {
  telegram_id: number
  username?: string
  first_name?: string
  last_name?: string
  has_active_subscription: boolean
  loyalty_level: string
  created_at: string
}

interface Props {
  api: { get: (url: string) => Promise<{ data: { users?: SearchResult[] } }> }
  onSelectUser: (telegramId: number) => void
}

const LEVELS: Record<string, string> = {
  none: '⚪', silver: '🥈', gold: '🥇', platinum: '💎'
}

export function BotUsersSearch({ api, onSelectUser }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)

  const search = async () => {
    if (query.length < 2) return
    setLoading(true)
    setSearched(true)
    try {
      const res = await api.get(`/admin/users/search?q=${encodeURIComponent(query)}`)
      setResults(res.data.users || [])
    } catch {
      setResults([])
    }
    setLoading(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') search()
  }

  return (
    <div className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-2xl border border-[#E8D4BA]/30 dark:border-[#3D3D3D] overflow-hidden">
      <div className="p-4 border-b border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
        <h3 className="font-medium text-[#5D4E3A] dark:text-[#E5E5E5] mb-3">🔍 Поиск пользователей бота</h3>
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#8B8279] dark:text-[#707070]" />
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="ID, @username или имя..."
              className="w-full pl-9 pr-4 py-2.5 bg-[#F5E6D3]/30 dark:bg-[#2A2A2A] border border-[#E8D4BA]/30 dark:border-[#3D3D3D] rounded-xl text-sm text-[#5D4E3A] dark:text-[#E5E5E5] placeholder:text-[#8B8279] dark:placeholder:text-[#707070] focus:outline-none focus:border-[#B08968]"
            />
          </div>
          <button
            onClick={search}
            disabled={loading || query.length < 2}
            className="px-4 py-2 bg-[#B08968] text-white rounded-xl text-sm font-medium disabled:opacity-50 flex items-center gap-2"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Найти'}
          </button>
        </div>
      </div>

      {results.length > 0 && (
        <div className="divide-y divide-[#E8D4BA]/20 dark:divide-[#3D3D3D] max-h-80 overflow-y-auto">
          {results.map(user => (
            <div
              key={user.telegram_id}
              onClick={() => onSelectUser(user.telegram_id)}
              className="p-4 flex items-center gap-3 hover:bg-[#F5E6D3]/30 dark:hover:bg-[#2A2A2A] cursor-pointer transition-colors"
            >
              <div className="w-10 h-10 rounded-full bg-[#B08968] text-white flex items-center justify-center font-medium">
                {user.first_name?.charAt(0) || '?'}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-[#5D4E3A] dark:text-[#E5E5E5]">{user.first_name || 'Без имени'}</span>
                  <span>{LEVELS[user.loyalty_level] || '⚪'}</span>
                  {user.has_active_subscription && <span className="text-xs px-1.5 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded">✅</span>}
                </div>
                {user.username && <p className="text-sm text-[#8B8279] dark:text-[#707070]">@{user.username}</p>}
              </div>
              <div className="text-right text-xs text-[#8B8279] dark:text-[#707070]">
                <p>ID: {user.telegram_id}</p>
                <p>{new Date(user.created_at).toLocaleDateString('ru-RU')}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {searched && !loading && results.length === 0 && (
        <div className="p-8 text-center text-[#8B8279] dark:text-[#707070]">Ничего не найдено</div>
      )}
    </div>
  )
}
