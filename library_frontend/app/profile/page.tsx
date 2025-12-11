'use client'

import { useAuthContext } from '@/contexts/AuthContext'
import { LoadingSpinner } from '@/components/shared'
import { LoyaltyCard, ReferralCard, PaymentHistoryCard, SettingsCard, PaymentModal } from '@/components/profile'
import { useState } from 'react'
import Link from 'next/link'

export default function ProfilePage() {
  const { user, loading, hasSubscription, logout } = useAuthContext()
  const [showPaymentModal, setShowPaymentModal] = useState(false)

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-[#FDFCFA] via-[#FBF8F3] to-[#F5EFE6] flex items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#FDFCFA] via-[#FBF8F3] to-[#F5EFE6] relative overflow-hidden">
      {/* Premium gradient orbs */}
      <div className="fixed -top-40 -right-40 w-[600px] h-[600px] bg-gradient-to-br from-[#E8D5C4]/30 via-[#D4C4B0]/15 to-transparent rounded-full blur-3xl pointer-events-none" />
      <div className="fixed -bottom-40 -left-40 w-[500px] h-[500px] bg-gradient-to-tr from-[#C9B89A]/15 to-transparent rounded-full blur-3xl pointer-events-none" />

      {/* Header */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-[#E8D4BA]/30">
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between">
          {/* Logo with Santa */}
          <Link href={hasSubscription ? "/" : "/profile"} prefetch={false} className="group relative">
            <img 
              src="/logolibrary.svg" 
              alt="LibriMomsClub" 
              className="h-10 w-auto group-hover:scale-105 transition-transform"
            />
            <span className="absolute -top-2 -left-1 text-xl transform -rotate-12">🎅</span>
          </Link>
          
          <div className="flex items-center gap-4">
            {hasSubscription && (
              <Link 
                href="/"
                prefetch={false}
                className="text-sm font-medium text-[#B08968] hover:text-[#8B7355] transition-colors flex items-center gap-1"
              >
                <span>📚</span> В библиотеку
              </Link>
            )}
            <button
              onClick={logout}
              className="text-sm text-[#8B8279] hover:text-[#5D4E3A] transition-colors"
            >
              Выйти
            </button>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-4xl mx-auto px-4 py-8">
        {/* Hero с профилем */}
        <div className="relative mb-8">
          <div className="absolute inset-0 bg-gradient-to-br from-[#B08968]/10 to-[#C9A882]/5 rounded-3xl blur-xl" />
          <div className="relative bg-white/90 backdrop-blur-sm rounded-3xl shadow-xl shadow-[#C9A882]/10 border border-[#E8D4BA]/40 p-8">
            <div className="flex flex-col md:flex-row items-center gap-6">
              {/* Avatar */}
              <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-br from-[#B08968] to-[#C9A882] rounded-full blur-md opacity-30" />
                <img
                  src={user?.avatar}
                  alt={user?.name}
                  className="relative w-24 h-24 rounded-full border-4 border-white shadow-lg object-cover"
                />
                {hasSubscription && (
                  <div className="absolute -bottom-1 -right-1 w-8 h-8 bg-gradient-to-br from-green-400 to-green-500 rounded-full flex items-center justify-center shadow-lg">
                    <span className="text-white text-sm">✓</span>
                  </div>
                )}
              </div>
              
              {/* Info */}
              <div className="text-center md:text-left flex-1">
                <h1 className="text-2xl font-bold text-[#2D2A26] mb-1">
                  Привет, {user?.name}! 👋
                </h1>
                {user?.username && (
                  <p className="text-[#8B8279] mb-3">@{user.username}</p>
                )}
                
                {/* Статус подписки */}
                {hasSubscription ? (
                  <div className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-green-50 to-emerald-50 rounded-full border border-green-200/50">
                    <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                    <span className="text-sm font-medium text-green-700">
                      Подписка активна
                      {user?.subscriptionDaysLeft !== undefined && user.subscriptionDaysLeft <= 36000 && (
                        <span className="text-green-600/70"> · {user.subscriptionDaysLeft} дней</span>
                      )}
                      {user?.subscriptionDaysLeft !== undefined && user.subscriptionDaysLeft > 36000 && (
                        <span className="text-green-600/70"> · безлимит ∞</span>
                      )}
                    </span>
                  </div>
                ) : (
                  <div className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-amber-50 to-orange-50 rounded-full border border-amber-200/50">
                    <span className="text-amber-500">⚠️</span>
                    <span className="text-sm font-medium text-amber-700">Нет активной подписки</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Cards Grid */}
        <div className="grid md:grid-cols-2 gap-6">
          {/* Подписка */}
          <div className="bg-white/90 backdrop-blur-sm rounded-2xl shadow-lg shadow-[#C9A882]/10 border border-[#E8D4BA]/40 p-6 hover:shadow-xl transition-shadow">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 bg-gradient-to-br from-[#B08968] to-[#C9A882] rounded-xl flex items-center justify-center">
                <span className="text-white text-lg">💳</span>
              </div>
              <h2 className="text-lg font-semibold text-[#2D2A26]">Подписка</h2>
            </div>
            
            {hasSubscription ? (
              <div className="space-y-4">
                <p className="text-sm text-[#5D4E3A]">
                  Вы можете продлить подписку заранее — дни добавятся к текущему сроку.
                </p>
                <button 
                  onClick={() => setShowPaymentModal(true)}
                  className="w-full py-3 bg-gradient-to-r from-[#B08968] via-[#A67C52] to-[#96704A] text-white font-semibold rounded-xl shadow-lg shadow-[#B08968]/25 hover:shadow-xl hover:-translate-y-0.5 transition-all duration-300"
                >
                  Продлить подписку
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                <p className="text-sm text-[#5D4E3A]">
                  Для доступа к библиотеке материалов оформите подписку MomsClub.
                </p>
                <button 
                  onClick={() => setShowPaymentModal(true)}
                  className="w-full py-3 bg-gradient-to-r from-[#B08968] via-[#A67C52] to-[#96704A] text-white font-semibold rounded-xl shadow-lg shadow-[#B08968]/25 hover:shadow-xl hover:-translate-y-0.5 transition-all duration-300"
                >
                  Оформить подписку
                </button>
                <p className="text-xs text-center text-[#8B8279]">
                  или{' '}
                  <a 
                    href="https://t.me/momsclubsubscribe_bot"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[#B08968] hover:underline font-medium"
                  >
                    оплатить через бота →
                  </a>
                </p>
              </div>
            )}
          </div>

          {/* Лояльность — показываем только если есть подписка */}
          {hasSubscription ? (
            <LoyaltyCard />
          ) : (
            <div className="bg-white/60 backdrop-blur-sm rounded-2xl shadow-lg shadow-[#C9A882]/10 border border-[#E8D4BA]/40 p-6 relative overflow-hidden">
              <div className="absolute inset-0 bg-gradient-to-br from-purple-500/5 to-pink-500/5" />
              <div className="relative">
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-10 h-10 bg-gradient-to-br from-purple-400 to-pink-400 rounded-xl flex items-center justify-center">
                    <span className="text-white text-lg">✨</span>
                  </div>
                  <h2 className="text-lg font-semibold text-[#2D2A26]">Преимущества подписки</h2>
                </div>
                
                <div className="space-y-3">
                  <div className="flex items-center gap-3 text-sm text-[#5D4E3A]">
                    <span className="text-lg">💎</span>
                    <span>Программа лояльности</span>
                  </div>
                  <div className="flex items-center gap-3 text-sm text-[#5D4E3A]">
                    <span className="text-lg">👥</span>
                    <span>Реферальная программа</span>
                  </div>
                  <div className="flex items-center gap-3 text-sm text-[#5D4E3A]">
                    <span className="text-lg">📚</span>
                    <span>100+ материалов</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Реферальная программа — для всех авторизованных */}
        <div className="mt-6">
          <ReferralCard />
        </div>

        {/* История платежей */}
        <div className="mt-6">
          <PaymentHistoryCard />
        </div>

        {/* Настройки */}
        <div className="mt-6">
          <SettingsCard />
        </div>

        {/* Support */}
        <div className="mt-8 text-center">
          <p className="text-sm text-[#8B8279]">
            Нужна помощь?{' '}
            <a 
              href="https://t.me/momsclubsupport"
              target="_blank"
              rel="noopener noreferrer"
              className="text-[#B08968] hover:underline font-medium"
            >
              Напишите в поддержку
            </a>
          </p>
        </div>
      </main>

      {/* Payment Modal */}
      <PaymentModal
        isOpen={showPaymentModal}
        onClose={() => setShowPaymentModal(false)}
        isFirstPayment={!user?.subscriptionDaysLeft}
        hasSubscription={hasSubscription}
      />
    </div>
  )
}
