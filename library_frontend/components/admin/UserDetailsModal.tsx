'use client'

interface SelectedUser {
  user: {
    id: number
    telegram_id: number
    first_name: string
    username?: string
    photo_url?: string
  }
  views: { title: string; viewed_at: string }[]
  favorites: string[]
  subscription_end?: string
  has_push: boolean
}

interface UserDetailsModalProps {
  user: SelectedUser
  onClose: () => void
}

export function UserDetailsModal({ user, onClose }: UserDetailsModalProps) {
  return (
    <div 
      className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" 
      onClick={onClose}
    >
      <div 
        className="bg-white rounded-2xl max-w-md w-full max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Заголовок с аватаром */}
        <div className="p-5 border-b border-[#E8D4BA]/30">
          <div className="flex items-center gap-4">
            {user.user.photo_url ? (
              <img src={user.user.photo_url} alt="" className="w-16 h-16 rounded-full" />
            ) : (
              <div className="w-16 h-16 rounded-full bg-[#B08968] text-white text-2xl flex items-center justify-center font-medium">
                {user.user.first_name?.charAt(0) || '?'}
              </div>
            )}
            <div>
              <h3 className="font-bold text-lg text-[#5D4E3A]">
                {user.user.first_name || 'Без имени'}
              </h3>
              {user.user.username && (
                <p className="text-sm text-[#8B8279]">@{user.user.username}</p>
              )}
              <div className="flex gap-2 mt-1">
                <span className="text-xs px-2 py-0.5 rounded-full bg-[#F5E6D3]">
                  {user.has_push ? '🔔 Push вкл' : '⚪ Push выкл'}
                </span>
                {user.subscription_end && (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700">
                    Подписка до {new Date(user.subscription_end).toLocaleDateString('ru-RU')}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
        
        {/* Контент */}
        <div className="p-5 space-y-4">
          {/* Последние просмотры */}
          <div>
            <h4 className="font-medium text-[#5D4E3A] mb-2">👁 Последние просмотры</h4>
            {user.views.length > 0 ? (
              <div className="space-y-1">
                {user.views.slice(0, 5).map((v, i) => (
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
            <h4 className="font-medium text-[#5D4E3A] mb-2">⭐ Избранное ({user.favorites.length})</h4>
            {user.favorites.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {user.favorites.map((f, i) => (
                  <span key={i} className="text-xs px-2 py-1 bg-[#F5E6D3] rounded-lg text-[#5D4E3A]">
                    {f}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-sm text-[#8B8279]">Пусто</p>
            )}
          </div>
        </div>

        {/* Кнопки */}
        <div className="p-5 border-t border-[#E8D4BA]/30 flex gap-2">
          {user.user.username && (
            <a
              href={`https://t.me/${user.user.username}`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 py-2 bg-[#0088cc] text-white rounded-xl font-medium text-center"
            >
              💬 Написать в Telegram
            </a>
          )}
          <button
            onClick={onClose}
            className="px-4 py-2 border border-[#E8D4BA] text-[#8B8279] rounded-xl"
          >
            Закрыть
          </button>
        </div>
      </div>
    </div>
  )
}
