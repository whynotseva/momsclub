'use client'

import { useState, useEffect } from 'react'
import { api } from '@/lib/api'

interface PaymentItem {
  id: number
  amount: number
  status: string
  payment_method?: string
  details?: string
  days?: number
  created_at: string
  admin_name?: string
}

interface PaymentHistory {
  payments: PaymentItem[]
  total_paid: number
  total_count: number
}

export function PaymentHistoryCard() {
  const [history, setHistory] = useState<PaymentHistory | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    const loadHistory = async () => {
      try {
        const response = await api.get('/auth/payments')
        setHistory(response.data)
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : 'Unknown error'
        console.error('[PaymentHistoryCard] Error:', err)
        setError(errorMessage)
      } finally {
        setLoading(false)
      }
    }
    loadHistory()
  }, [])

  const formatDate = (dateStr: string) => {
    try {
      const date = new Date(dateStr)
      return date.toLocaleDateString('ru-RU', {
        day: 'numeric',
        month: 'short',
        year: 'numeric'
      })
    } catch {
      return dateStr
    }
  }

  const formatMoney = (amount: number) => {
    return amount.toLocaleString('ru-RU') + ' ₽'
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'success':
        return <span className="px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded-full">Оплачено</span>
      case 'failed':
        return <span className="px-2 py-0.5 bg-red-100 text-red-700 text-xs rounded-full">Отменён</span>
      case 'pending':
        return <span className="px-2 py-0.5 bg-yellow-100 text-yellow-700 text-xs rounded-full">Ожидает</span>
      default:
        return <span className="px-2 py-0.5 bg-gray-100 text-gray-700 text-xs rounded-full">{status}</span>
    }
  }

  const getMethodIcon = (method?: string) => {
    switch (method) {
      case 'yookassa':
      case 'youkassa':
      case 'prodamus':
        return '💳'
      case 'youkassa_autopay':
        return '🔄'
      case 'admin':
        return '🎁'
      case 'referral_balance':
        return '💰'
      default:
        return '💳'
    }
  }

  const getMethodLabel = (payment: PaymentItem) => {
    switch (payment.payment_method) {
      case 'yookassa':
      case 'youkassa':
        return 'ЮKassa'
      case 'prodamus':
        return 'Prodamus'
      case 'youkassa_autopay':
        return 'Автопродление'
      case 'admin':
        return payment.admin_name ? `Подарок от ${payment.admin_name}` : 'Подарок от админа'
      case 'referral_balance':
        return 'Оплата балансом'
      default:
        return payment.payment_method || 'Оплата'
    }
  }

  if (loading) {
    return (
      <div className="bg-white/90 backdrop-blur-sm rounded-2xl shadow-lg shadow-[#C9A882]/10 border border-[#E8D4BA]/40 p-6">
        <div className="animate-pulse space-y-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-[#E8D4BA]/50 rounded-xl" />
            <div className="h-5 bg-[#E8D4BA]/50 rounded w-36" />
          </div>
          <div className="space-y-2">
            <div className="h-12 bg-[#E8D4BA]/30 rounded-xl" />
            <div className="h-12 bg-[#E8D4BA]/30 rounded-xl" />
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-white/90 backdrop-blur-sm rounded-2xl shadow-lg shadow-[#C9A882]/10 border border-[#E8D4BA]/40 p-6">
        <div className="flex items-center gap-3 mb-2">
          <span className="text-xl">📋</span>
          <h2 className="text-lg font-semibold text-[#2D2A26]">История платежей</h2>
        </div>
        <p className="text-sm text-[#8B8279]">Не удалось загрузить данные</p>
      </div>
    )
  }

  if (!history || history.payments.length === 0) {
    return (
      <div className="bg-white/90 backdrop-blur-sm rounded-2xl shadow-lg shadow-[#C9A882]/10 border border-[#E8D4BA]/40 p-6">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 bg-gradient-to-br from-[#B08968] to-[#C9A882] rounded-xl flex items-center justify-center">
            <span className="text-white text-lg">📋</span>
          </div>
          <div>
            <h2 className="text-lg font-semibold text-[#2D2A26]">История платежей</h2>
            <p className="text-sm text-[#8B8279]">Пока нет платежей</p>
          </div>
        </div>
      </div>
    )
  }

  const displayedPayments = expanded ? history.payments : history.payments.slice(0, 3)

  return (
    <div className="bg-white/90 backdrop-blur-sm rounded-2xl shadow-lg shadow-[#C9A882]/10 border border-[#E8D4BA]/40 p-6 hover:shadow-xl transition-shadow">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-to-br from-[#B08968] to-[#C9A882] rounded-xl flex items-center justify-center">
            <span className="text-white text-lg">📋</span>
          </div>
          <div>
            <h2 className="text-lg font-semibold text-[#2D2A26]">История платежей</h2>
            <p className="text-sm text-[#8B8279]">Всего оплачено: {formatMoney(history.total_paid)}</p>
          </div>
        </div>
      </div>

      {/* Payments List */}
      <div className="space-y-2">
        {displayedPayments.map((payment) => (
          <div
            key={payment.id}
            className="flex items-center justify-between p-3 bg-[#FAF6F1] rounded-xl"
          >
            <div className="flex items-center gap-3">
              <span className="text-xl">{getMethodIcon(payment.payment_method)}</span>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-medium text-[#2D2A26]">
                    {payment.amount > 0 ? formatMoney(payment.amount) : 'Бесплатно'}
                  </span>
                  {getStatusBadge(payment.status)}
                </div>
                <p className="text-xs text-[#8B8279]">
                  {formatDate(payment.created_at)}
                  {payment.days && ` • ${payment.days} дней`}
                  {` • ${getMethodLabel(payment)}`}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Show More Button */}
      {history.payments.length > 3 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full mt-4 py-2 text-sm text-[#B08968] hover:text-[#8B7355] transition-colors"
        >
          {expanded ? 'Свернуть ↑' : `Показать ещё (${history.payments.length - 3}) ↓`}
        </button>
      )}
    </div>
  )
}
