'use client'

import { useState } from 'react'
import { X } from 'lucide-react'

interface UserCard {
  id: number
  telegram_id: number
  username?: string
  first_name?: string
  last_name?: string
  phone?: string
  email?: string
  created_at: string
  subscription?: {
    end_date: string
    days_left: number
    price: number
  }
  has_active_subscription: boolean
  is_recurring_active: boolean
  autopay_streak: number
  loyalty: {
    level: string
    days_in_club: number
  }
  referral: {
    referral_balance: number
    referrals_count: number
    total_earned_referral: number
  }
  badges: { badge_type: string }[]
  total_payments_count: number
  total_paid_amount: number
}

interface Props {
  user: UserCard
  onClose: () => void
  onRefresh: () => void
  api: { post: (url: string, data?: Record<string, unknown>) => Promise<{ data: Record<string, unknown> }> }
}

const LEVELS: Record<string, string> = {
  none: '⚪ Нет', silver: '🥈 Silver', gold: '🥇 Gold', platinum: '💎 Platinum'
}

export function BotUserCard({ user, onClose, onRefresh, api }: Props) {
  const [days, setDays] = useState(7)
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState('')

  const extend = async () => {
    setLoading(true)
    try {
      await api.post(`/admin/users/${user.telegram_id}/subscription/extend`, { days })
      setMsg(`✅ +${days} дней`)
      onRefresh()
    } catch { setMsg('❌ Ошибка') }
    setLoading(false)
  }

  const toggleAuto = async () => {
    setLoading(true)
    try {
      const r = await api.post(`/admin/users/${user.telegram_id}/autorenew/toggle`)
      setMsg(`✅ Автопродление ${r.data.is_recurring_active ? 'вкл' : 'выкл'}`)
      onRefresh()
    } catch { setMsg('❌ Ошибка') }
    setLoading(false)
  }

  const setLevel = async (level: string) => {
    setLoading(true)
    try {
      await api.post(`/admin/users/${user.telegram_id}/loyalty/level`, { level })
      setMsg(`✅ Уровень: ${LEVELS[level]}`)
      onRefresh()
    } catch { setMsg('❌ Ошибка') }
    setLoading(false)
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white dark:bg-[#1E1E1E] rounded-2xl max-w-lg w-full max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="p-4 border-b border-[#E8D4BA]/30 dark:border-[#3D3D3D] flex justify-between items-start">
          <div>
            <h3 className="font-bold text-lg dark:text-[#E5E5E5]">{user.first_name} {user.last_name}</h3>
            {user.username && <a href={`https://t.me/${user.username}`} target="_blank" className="text-sm text-[#B08968]">@{user.username}</a>}
            <div className="flex gap-2 mt-2 text-xs">
              <span className={`px-2 py-0.5 rounded-full ${user.has_active_subscription ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                {user.has_active_subscription ? '✅ Подписка' : '❌ Нет подписки'}
              </span>
              <span className="px-2 py-0.5 rounded-full bg-gray-100 dark:bg-[#2A2A2A] dark:text-[#E5E5E5]">{LEVELS[user.loyalty.level]}</span>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-gray-100 dark:hover:bg-[#2A2A2A] rounded-lg"><X className="w-5 h-5 dark:text-[#E5E5E5]" /></button>
        </div>

        {msg && <div className="mx-4 mt-3 p-2 bg-[#F5E6D3] dark:bg-[#2A2A2A] rounded-lg text-sm dark:text-[#E5E5E5]">{msg}</div>}

        <div className="p-4 space-y-4">
          {/* Подписка */}
          <section className="bg-[#FDFCFA] dark:bg-[#2A2A2A] rounded-xl p-3 border border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
            <h4 className="font-medium mb-2 dark:text-[#E5E5E5]">💳 Подписка</h4>
            {user.subscription ? (
              <div className="text-sm space-y-1 dark:text-[#B0B0B0]">
                <p>До: <b>{new Date(user.subscription.end_date).toLocaleDateString('ru-RU')}</b> ({user.subscription.days_left} дн)</p>
                <p>Автопродление: {user.is_recurring_active ? '✅' : '❌'} (серия: {user.autopay_streak})</p>
              </div>
            ) : <p className="text-sm text-gray-500 dark:text-[#707070]">Нет подписки</p>}
            <div className="flex gap-2 mt-3">
              <input type="number" value={days} onChange={e => setDays(+e.target.value)} className="w-16 px-2 py-1 border dark:border-[#3D3D3D] rounded dark:bg-[#1E1E1E] dark:text-[#E5E5E5]" />
              <button onClick={extend} disabled={loading} className="px-3 py-1 bg-[#B08968] text-white rounded text-sm">+Дни</button>
              <button onClick={toggleAuto} disabled={loading} className="px-3 py-1 bg-gray-200 dark:bg-[#3D3D3D] dark:text-[#E5E5E5] rounded text-sm">🔄 Авто</button>
            </div>
          </section>

          {/* Лояльность */}
          <section className="bg-[#FDFCFA] dark:bg-[#2A2A2A] rounded-xl p-3 border border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
            <h4 className="font-medium mb-2 dark:text-[#E5E5E5]">⭐ Лояльность</h4>
            <p className="text-sm mb-2 dark:text-[#B0B0B0]">Текущий: {LEVELS[user.loyalty.level]} • В клубе: {user.loyalty.days_in_club} дн</p>
            <div className="flex gap-1 flex-wrap">
              {['none','silver','gold','platinum'].map(l => (
                <button key={l} onClick={() => setLevel(l)} disabled={loading || user.loyalty.level === l}
                  className={`px-2 py-1 rounded text-xs ${user.loyalty.level === l ? 'bg-[#B08968] text-white' : 'bg-gray-100 dark:bg-[#3D3D3D] dark:text-[#E5E5E5] hover:bg-gray-200 dark:hover:bg-[#4A4A4A]'}`}>
                  {LEVELS[l]}
                </button>
              ))}
            </div>
          </section>

          {/* Рефералы */}
          <section className="bg-[#FDFCFA] dark:bg-[#2A2A2A] rounded-xl p-3 border border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
            <h4 className="font-medium mb-2 dark:text-[#E5E5E5]">👥 Рефералы</h4>
            <div className="text-sm grid grid-cols-3 gap-2">
              <div className="text-center p-2 bg-white dark:bg-[#1E1E1E] rounded-lg">
                <div className="font-bold dark:text-[#E5E5E5]">{user.referral.referrals_count}</div>
                <div className="text-xs text-gray-500 dark:text-[#707070]">Приглашено</div>
              </div>
              <div className="text-center p-2 bg-white dark:bg-[#1E1E1E] rounded-lg">
                <div className="font-bold dark:text-[#E5E5E5]">{user.referral.referral_balance}₽</div>
                <div className="text-xs text-gray-500 dark:text-[#707070]">Баланс</div>
              </div>
              <div className="text-center p-2 bg-white dark:bg-[#1E1E1E] rounded-lg">
                <div className="font-bold dark:text-[#E5E5E5]">{user.referral.total_earned_referral}₽</div>
                <div className="text-xs text-gray-500 dark:text-[#707070]">Всего</div>
              </div>
            </div>
          </section>

          {/* Статистика */}
          <section className="bg-[#FDFCFA] dark:bg-[#2A2A2A] rounded-xl p-3 border border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
            <h4 className="font-medium mb-2 dark:text-[#E5E5E5]">📊 Статистика</h4>
            <div className="text-sm dark:text-[#B0B0B0]">
              <p>Платежей: {user.total_payments_count} на {user.total_paid_amount}₽</p>
              <p>Достижений: {user.badges.length}</p>
              <p>В системе с: {new Date(user.created_at).toLocaleDateString('ru-RU')}</p>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
