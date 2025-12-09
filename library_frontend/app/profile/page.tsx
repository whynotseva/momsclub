'use client'

import { useAuthContext } from '@/contexts/AuthContext'
import { LoadingSpinner } from '@/components/shared'
import Link from 'next/link'

export default function ProfilePage() {
  const { user, loading, hasSubscription } = useAuthContext()

  if (loading) {
    return (
      <div className="min-h-screen bg-[#FDF8F3] flex items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#FDF8F3]">
      {/* Header */}
      <div className="bg-white/80 backdrop-blur-xl border-b border-[#E8D4BA]/30 px-4 py-3">
        <div className="max-w-2xl mx-auto flex items-center justify-between">
          <h1 className="text-xl font-semibold text-[#5D4E3A]">Личный кабинет</h1>
          {hasSubscription && (
            <Link 
              href="/"
              className="text-sm text-[#B08968] hover:text-[#8B7355] transition-colors"
            >
              ← В библиотеку
            </Link>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="max-w-2xl mx-auto p-4 space-y-4">
        {/* Карточка профиля */}
        <div className="bg-white/80 backdrop-blur-xl rounded-2xl p-5 border border-[#E8D4BA]/30">
          <div className="flex items-center gap-4">
            <img
              src={user?.avatar}
              alt={user?.name}
              className="w-16 h-16 rounded-full border-2 border-[#E8D4BA]"
            />
            <div>
              <h2 className="text-lg font-semibold text-[#5D4E3A]">
                {user?.name}
              </h2>
              {user?.username && (
                <p className="text-sm text-[#8B8279]">@{user.username}</p>
              )}
            </div>
          </div>
        </div>

        {/* Статус подписки */}
        <div className="bg-white/80 backdrop-blur-xl rounded-2xl p-5 border border-[#E8D4BA]/30">
          <h3 className="font-semibold text-[#5D4E3A] mb-3">Подписка</h3>
          
          {hasSubscription ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-green-600">✓</span>
                <span className="text-[#5D4E3A]">Активна</span>
              </div>
              {user?.subscriptionDaysLeft !== undefined && (
                <p className="text-sm text-[#8B8279]">
                  Осталось дней: {user.subscriptionDaysLeft > 36000 ? '∞' : user.subscriptionDaysLeft}
                </p>
              )}
              <button className="w-full py-3 bg-gradient-to-r from-[#B08968] to-[#A67C52] text-white rounded-xl font-medium hover:opacity-90 transition-opacity">
                Продлить заранее
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-red-500">✗</span>
                <span className="text-[#5D4E3A]">Нет активной подписки</span>
              </div>
              <p className="text-sm text-[#8B8279]">
                Для доступа к библиотеке оформите подписку
              </p>
              <button className="w-full py-3 bg-gradient-to-r from-[#B08968] to-[#A67C52] text-white rounded-xl font-medium hover:opacity-90 transition-opacity">
                Оформить подписку
              </button>
              <p className="text-xs text-center text-[#8B8279]">
                или оплатить через{' '}
                <a 
                  href="https://t.me/momsclubsubscribe_bot"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[#B08968] hover:underline"
                >
                  бота
                </a>
              </p>
            </div>
          )}
        </div>

        {/* Заглушка — скоро будет больше */}
        <div className="bg-white/80 backdrop-blur-xl rounded-2xl p-5 border border-[#E8D4BA]/30 opacity-50">
          <p className="text-center text-[#8B8279] text-sm">
            🚧 Скоро здесь появится: программа лояльности, реферальная программа, история платежей
          </p>
        </div>
      </div>
    </div>
  )
}
