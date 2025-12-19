'use client'

import { useState, useEffect } from 'react'
import { Users, CreditCard, Clock, Wallet, TrendingUp, RefreshCw } from 'lucide-react'

interface BotStats {
  total_users: number
  active_subscriptions: number
  expiring_soon: number
  with_autorenew: number
  pending_withdrawals: number
  monthly_revenue: number
}

interface Subscription {
  telegram_id: number
  username?: string
  first_name?: string
  is_recurring_active: boolean
  end_date: string
  price: number
  days_left: number
}

interface Withdrawal {
  id: number
  amount: number
  payment_method: string
  payment_details: string
  status: string
  created_at: string
  user: { telegram_id: number; username?: string; first_name?: string }
}

interface Props {
  api: { 
    get: (url: string) => Promise<{ data: unknown }>
    post: (url: string, data?: Record<string, unknown>) => Promise<{ data: unknown }>
  }
  onSelectUser: (telegramId: number) => void
}

export function BotStatsTab({ api, onSelectUser }: Props) {
  const [stats, setStats] = useState<BotStats | null>(null)
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([])
  const [withdrawals, setWithdrawals] = useState<Withdrawal[]>([])
  const [subFilter, setSubFilter] = useState<'active' | 'expiring' | 'expired'>('expiring')
  const [loading, setLoading] = useState(false)

  const loadStats = async () => {
    try {
      const res = await api.get('/admin/bot-stats')
      setStats(res.data as BotStats)
    } catch (e) { console.error(e) }
  }

  const loadSubscriptions = async (filter: string) => {
    try {
      const res = await api.get(`/admin/subscriptions?filter=${filter}`)
      setSubscriptions(res.data as Subscription[])
    } catch (e) { console.error(e) }
  }

  const loadWithdrawals = async () => {
    try {
      const res = await api.get('/admin/withdrawals?status=pending')
      setWithdrawals(res.data as Withdrawal[])
    } catch (e) { console.error(e) }
  }

  useEffect(() => {
    loadStats()
    loadSubscriptions(subFilter)
    loadWithdrawals()
  }, [])

  useEffect(() => {
    loadSubscriptions(subFilter)
  }, [subFilter])

  const handleApprove = async (id: number) => {
    setLoading(true)
    try {
      await api.post(`/admin/withdrawals/${id}/approve`)
      loadWithdrawals()
      loadStats()
    } catch (e) { console.error(e) }
    setLoading(false)
  }

  const handleReject = async (id: number) => {
    const reason = prompt('Причина отклонения:')
    if (reason === null) return
    setLoading(true)
    try {
      await api.post(`/admin/withdrawals/${id}/reject?reason=${encodeURIComponent(reason)}`)
      loadWithdrawals()
      loadStats()
    } catch (e) { console.error(e) }
    setLoading(false)
  }

  return (
    <div className="space-y-6">
      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <StatCard icon={<Users className="w-5 h-5" />} label="Пользователей" value={stats.total_users} />
          <StatCard icon={<CreditCard className="w-5 h-5" />} label="Подписок" value={stats.active_subscriptions} color="green" />
          <StatCard icon={<Clock className="w-5 h-5" />} label="Истекает" value={stats.expiring_soon} color="orange" />
          <StatCard icon={<RefreshCw className="w-5 h-5" />} label="Автопрод." value={stats.with_autorenew} color="blue" />
          <StatCard icon={<Wallet className="w-5 h-5" />} label="Заявок" value={stats.pending_withdrawals} color="purple" />
          <StatCard icon={<TrendingUp className="w-5 h-5" />} label="За месяц" value={`${stats.monthly_revenue}₽`} color="green" />
        </div>
      )}

      {/* Subscriptions */}
      <div className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-2xl border border-[#E8D4BA]/30 dark:border-[#3D3D3D] overflow-hidden">
        <div className="p-4 border-b border-[#E8D4BA]/30 dark:border-[#3D3D3D] flex items-center justify-between">
          <h3 className="font-medium text-[#5D4E3A] dark:text-[#E5E5E5]">📋 Подписки</h3>
          <div className="flex gap-1">
            {(['expiring', 'active', 'expired'] as const).map(f => (
              <button key={f} onClick={() => setSubFilter(f)}
                className={`px-3 py-1 rounded-lg text-xs ${subFilter === f ? 'bg-[#B08968] text-white' : 'bg-[#F5E6D3]/50 dark:bg-[#2A2A2A] text-[#8B8279] dark:text-[#B0B0B0]'}`}>
                {f === 'expiring' ? '⏰ Скоро' : f === 'active' ? '✅ Активные' : '❌ Истекшие'}
              </button>
            ))}
          </div>
        </div>
        <div className="divide-y divide-[#E8D4BA]/20 dark:divide-[#3D3D3D] max-h-60 overflow-y-auto">
          {subscriptions.map(s => (
            <div key={s.telegram_id} onClick={() => onSelectUser(s.telegram_id)}
              className="p-3 flex items-center justify-between hover:bg-[#F5E6D3]/30 dark:hover:bg-[#2A2A2A] cursor-pointer">
              <div>
                <span className="font-medium text-[#5D4E3A] dark:text-[#E5E5E5]">{s.first_name || 'Без имени'}</span>
                {s.username && <span className="text-sm text-[#8B8279] dark:text-[#707070] ml-2">@{s.username}</span>}
                {s.is_recurring_active && <span className="ml-2 text-xs">🔄</span>}
              </div>
              <div className="text-right text-sm">
                <div className={s.days_left <= 3 ? 'text-red-500 font-medium' : 'text-[#5D4E3A] dark:text-[#E5E5E5]'}>
                  {s.days_left > 0 ? `${s.days_left} дн` : 'Истекла'}
                </div>
                <div className="text-xs text-[#8B8279] dark:text-[#707070]">{new Date(s.end_date).toLocaleDateString('ru-RU')}</div>
              </div>
            </div>
          ))}
          {subscriptions.length === 0 && <div className="p-4 text-center text-[#8B8279] dark:text-[#707070]">Пусто</div>}
        </div>
      </div>

      {/* Withdrawals */}
      <div className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-2xl border border-[#E8D4BA]/30 dark:border-[#3D3D3D] overflow-hidden">
        <div className="p-4 border-b border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
          <h3 className="font-medium text-[#5D4E3A] dark:text-[#E5E5E5]">💰 Заявки на вывод ({withdrawals.length})</h3>
        </div>
        <div className="divide-y divide-[#E8D4BA]/20 dark:divide-[#3D3D3D]">
          {withdrawals.map(w => (
            <div key={w.id} className="p-4">
              <div className="flex items-center justify-between mb-2">
                <div onClick={() => onSelectUser(w.user.telegram_id)} className="cursor-pointer hover:text-[#B08968]">
                  <span className="font-medium dark:text-[#E5E5E5]">{w.user.first_name}</span>
                  {w.user.username && <span className="text-sm text-[#8B8279] dark:text-[#707070] ml-1">@{w.user.username}</span>}
                </div>
                <span className="font-bold text-[#B08968]">{w.amount}₽</span>
              </div>
              <div className="text-sm text-[#8B8279] dark:text-[#707070] mb-3">
                {w.payment_method}: {w.payment_details}
              </div>
              <div className="flex gap-2">
                <button onClick={() => handleApprove(w.id)} disabled={loading}
                  className="flex-1 py-2 bg-green-500 text-white rounded-xl text-sm font-medium hover:bg-green-600 disabled:opacity-50">
                  ✅ Одобрить
                </button>
                <button onClick={() => handleReject(w.id)} disabled={loading}
                  className="flex-1 py-2 bg-red-500 text-white rounded-xl text-sm font-medium hover:bg-red-600 disabled:opacity-50">
                  ❌ Отклонить
                </button>
              </div>
            </div>
          ))}
          {withdrawals.length === 0 && <div className="p-4 text-center text-[#8B8279] dark:text-[#707070]">Нет заявок</div>}
        </div>
      </div>
    </div>
  )
}

function StatCard({ icon, label, value, color = 'default' }: { 
  icon: React.ReactNode; label: string; value: string | number; color?: string 
}) {
  const colors: Record<string, string> = {
    default: 'from-[#B08968] to-[#96704A]',
    green: 'from-green-500 to-green-600',
    orange: 'from-orange-400 to-orange-500',
    blue: 'from-blue-500 to-blue-600',
    purple: 'from-purple-500 to-purple-600'
  }
  return (
    <div className="bg-white/80 dark:bg-[#1E1E1E]/80 backdrop-blur-xl rounded-xl p-3 border border-[#E8D4BA]/30 dark:border-[#3D3D3D]">
      <div className={`w-8 h-8 rounded-lg bg-gradient-to-br ${colors[color]} text-white flex items-center justify-center mb-2`}>
        {icon}
      </div>
      <div className="text-xl font-bold text-[#5D4E3A] dark:text-[#E5E5E5]">{value}</div>
      <div className="text-xs text-[#8B8279] dark:text-[#707070]">{label}</div>
    </div>
  )
}
